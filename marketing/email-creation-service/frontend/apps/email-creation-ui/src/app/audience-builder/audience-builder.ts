import { Component, ElementRef, EventEmitter, OnDestroy, Output, ViewChild, effect, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type {
  AudienceListInfo,
  ComposeMasterListResponse,
  DiscoveredList,
  DiscoveryStreamEvent,
  ExistingMasterList,
  LastSentEmail,
  PreviewCountResponse,
  QaResultResponse,
  SuppressionList,
} from '@email-creation/shared';
import { ListsService } from '../lists.service';
import { AudienceBuilderService } from './audience-builder.service';

/** One list the user has added to the audience being composed. */
interface SelectedList {
  id: string;
  name: string;
}

// Display metadata for the discovery card grid — grouping order, section
// labels/descriptions, mirroring legacy audience-builder.js's SIGNAL_ORDER /
// SIGNAL_LABELS / SIGNAL_DESC (kept local to this component since these are
// pure UI strings, not part of the shared API contract).
const SIGNAL_ORDER = [
  'last_sent',
  'event_registration',
  'event_speakers',
  'project_opt_in',
  'lf_newsletter_opt_in',
  'education_enrollment',
  'page_view',
  'uncertain',
  'added',
];
const SIGNAL_LABELS: Record<string, string> = {
  last_sent: 'Used In Past Sends',
  project_opt_in: 'Project Opt-In',
  lf_newsletter_opt_in: 'LF Newsletter Opt-In',
  event_registration: 'Event Registration',
  education_enrollment: 'Education Enrollment',
  page_view: 'Page View',
  event_speakers: 'Event Speakers',
  uncertain: 'Uncertain',
  added: 'Manually Added',
};
const SIGNAL_DESC: Record<string, string> = {
  last_sent: 'Used in a past send for this event but not classified under the signals below',
  project_opt_in: "Opted into this project's own subscription type",
  lf_newsletter_opt_in: 'Opted into the Linux Foundation newsletter',
  event_registration: 'All-time registrants for this event',
  education_enrollment: 'Enrolled in related education content',
  page_view: "Viewed this event's page",
  event_speakers: 'Speakers for this event specifically',
  uncertain: 'Needs manual review before including',
  added: 'Manually added via search',
};

// Every generated prompt ends with the same explicit no-suppression note:
// these are single-signal inclusion lists built one at a time from the
// "Qualifying lists not found" panel, not the final send audience.
// Suppressions must be applied exactly once, later, on the master list that
// combines these — never baked into an individual signal list here.
const NO_SUPPRESSION_NOTE =
  ' This is a single inclusion list for one signal only — it will be combined into a master audience later. Do not add any suppression filters or a Combined Suppression list to it; suppressions apply only at the master-list level.';

// Missing-signal descriptions + prompt builders for the "Qualifying lists not
// found" section (event_speakers is excluded — it gets its own always-on
// 3-row status widget below instead, see speakerScopeStatus() /
// speakerScopePrompt()). Mirrors legacy audience-builder.js's SIGNAL_INFO.
const MISSING_SIGNAL_INFO: Record<string, { label: string; description: string; prompt: (eventUrl: string) => string }> = {
  project_opt_in: {
    label: 'Project Opt-In',
    description: "Contacts opted into this project's own email subscription type (not the general LF newsletter).",
    prompt: (eventUrl) =>
      `Build a list of contacts opted into this project's own email subscription type (project-specific opt-in, not the general Linux Foundation newsletter) for the event at ${eventUrl}.${NO_SUPPRESSION_NOTE}`,
  },
  lf_newsletter_opt_in: {
    label: 'LF Newsletter Opt-In',
    description: 'Contacts opted into the Linux Foundation Newsletter subscription type.',
    prompt: (eventUrl) =>
      `Build a list of contacts opted into the Linux Foundation Newsletter subscription type, relevant to the event at ${eventUrl}.${NO_SUPPRESSION_NOTE}`,
  },
  event_registration: {
    label: 'Event Registration',
    description: 'All-time registrants for this event, across all past editions.',
    prompt: (eventUrl) => `Build a list of all-time registrants (all editions) for the event at ${eventUrl}.${NO_SUPPRESSION_NOTE}`,
  },
  education_enrollment: {
    label: 'Education Enrollment',
    description: "Contacts enrolled in LFX Education courses related to this event's topic area.",
    prompt: (eventUrl) =>
      `Build a list of contacts enrolled in LFX Education courses related to the topic area of the event at ${eventUrl}.${NO_SUPPRESSION_NOTE}`,
  },
  page_view: {
    label: 'Page View',
    description: "Contacts who viewed this event's page (page-view based segment).",
    prompt: (eventUrl) => `Build a page-view based list of contacts who viewed the event page at ${eventUrl}.${NO_SUPPRESSION_NOTE}`,
  },
};

const SPEAKER_SCOPES: { key: string; label: string }[] = [
  { key: 'current', label: 'Current event speakers' },
  { key: 'past', label: 'Past event speakers' },
  { key: 'current_past', label: 'Current + Past event speakers' },
];
const SPEAKER_SCOPE_LABELS: Record<string, string> = { current: 'Current', past: 'Past', current_past: 'Current + Past' };

/** Prompt builder for the event_speakers signal — the only one that's scope-aware. */
function speakerScopePrompt(eventUrl: string, scopeKey: string): string {
  const label = SPEAKER_SCOPE_LABELS[scopeKey] ?? SPEAKER_SCOPE_LABELS['current_past'];
  const scopeNote =
    scopeKey === 'current'
      ? ' Only include speakers from the CURRENT/upcoming edition of this event — exclude speakers from any past edition.'
      : scopeKey === 'past'
        ? ' Only include speakers from PAST editions of this event — exclude speakers from the current/upcoming edition.'
        : ' Include speakers from both the current/upcoming edition and every past edition of this event.';
  return `Build a list of contacts who are speakers (not general registrants) for the event at ${eventUrl}.${scopeNote} SPEAKER SCOPE: ${label}.${NO_SUPPRESSION_NOTE}`;
}

// Suppression-category display metadata — section label + rank order for the
// grid grouping (mirrors legacy loadSuppressionLists' rank object: an
// existing per-event suppression list is the strongest signal, then
// brand-scoped opt-outs, then current registrants, then generic terms).
const SUPPRESSION_CATEGORY_RANK: Record<string, number> = {
  event_specific: 0,
  brand: 1,
  current_registrants: 2,
  standard: 3,
};
const SUPPRESSION_CATEGORY_LABELS: Record<string, string> = {
  event_specific: 'Existing suppression for this event',
  brand: 'LF Global Opt-Out',
  current_registrants: 'Current Registrants',
  standard: 'Standard',
};

// A card's scope satisfies a requested scope if they match exactly, or if
// the card covers both editions (current_past is a superset of either). A
// blank/missing scope is treated as current_past, matching the backend's
// own safest-default rule.
function speakerCardCoversScope(card: DiscoveredList, scopeKey: string): boolean {
  const s = card.scope || 'current_past';
  return s === 'current_past' || s === scopeKey;
}

@Component({
  selector: 'app-audience-builder',
  imports: [FormsModule],
  templateUrl: './audience-builder.html',
  styleUrl: './audience-builder.scss',
})
export class AudienceBuilder implements OnDestroy {
  /** Emits a pre-filled Custom Audience request string when "Create list" is clicked for a missing signal. */
  @Output() readonly createListRequested = new EventEmitter<string>();

  // ── URL-based discovery ──────────────────────────────────────────────
  // The main entry point: paste an event/campaign URL, discovery finds
  // existing HubSpot lists per signal via the Python backend's SSE job,
  // and on completion auto-populates brandShort/eventName below and
  // triggers the same context loads loadContext() does manually.
  protected readonly eventUrl = signal('');
  protected readonly discoverUrlError = signal<string | null>(null);
  protected readonly discovering = signal(false);
  protected readonly discoverError = signal<string | null>(null);
  protected readonly discoverTicker = signal<string[]>([]);
  protected readonly discoveredCards = signal<DiscoveredList[]>([]);
  protected readonly missingSignals = signal<string[]>([]);
  protected readonly discoveryRan = signal(false);
  protected readonly SPEAKER_SCOPES = SPEAKER_SCOPES;

  @ViewChild('discoverTickerEl') private discoverTickerEl?: ElementRef<HTMLDivElement>;
  private eventSource: EventSource | null = null;

  // Event context. Suppression lists, last-sent emails, and existing master
  // lists are all looked up by brand + event name (matches the legacy
  // audience-builder.js contract).
  protected readonly brandShort = signal('');
  protected readonly eventName = signal('');
  protected readonly contextLoaded = signal(false);

  // Manual list search + add (reuses the same lists/search endpoint the
  // status/search panel already uses).
  protected readonly searchQuery = signal('');
  protected readonly searchResults = signal<AudienceListInfo[]>([]);
  protected readonly searching = signal(false);
  protected readonly searchError = signal<string | null>(null);

  // The audience being assembled.
  protected readonly selected = signal<SelectedList[]>([]);

  // Suppression lists are loaded but never pre-checked — the user must
  // explicitly opt each one in before it's sent to HubSpot.
  protected readonly suppressionLists = signal<SuppressionList[]>([]);
  protected readonly suppressionLoading = signal(false);
  protected readonly suppressionError = signal<string | null>(null);
  protected readonly excludedListIds = signal<Set<string>>(new Set());

  protected readonly lastSentEmails = signal<LastSentEmail[]>([]);
  protected readonly lastSentLoading = signal(false);
  protected readonly lastSentError = signal<string | null>(null);

  protected readonly existingMasterLists = signal<ExistingMasterList[]>([]);
  protected readonly existingLoading = signal(false);
  protected readonly existingError = signal<string | null>(null);

  protected readonly previewResult = signal<PreviewCountResponse | null>(null);
  protected readonly previewLoading = signal(false);
  protected readonly previewError = signal<string | null>(null);

  // Exact-count for the Suppression & Exclusions stat row — mirrors
  // previewResult/previewLoading above but scoped to excludedListIds().
  protected readonly suppressionExactResult = signal<PreviewCountResponse | null>(null);
  protected readonly suppressionExactLoading = signal(false);
  protected readonly suppressionExactError = signal<string | null>(null);

  protected readonly masterListName = signal('');
  protected readonly composeResult = signal<ComposeMasterListResponse | null>(null);
  protected readonly composeLoading = signal(false);
  protected readonly composeError = signal<string | null>(null);

  protected readonly targetsEU = signal(false);
  protected readonly targetsCA = signal(false);
  protected readonly qaResult = signal<QaResultResponse | null>(null);
  protected readonly qaLoading = signal(false);
  protected readonly qaError = signal<string | null>(null);

  constructor(
    private readonly listsService: ListsService,
    private readonly audienceService: AudienceBuilderService,
  ) {
    // Auto-scroll the discovery log ticker to its latest line.
    effect(() => {
      this.discoverTicker();
      queueMicrotask(() => {
        const el = this.discoverTickerEl?.nativeElement;
        if (el) el.scrollTop = el.scrollHeight;
      });
    });
  }

  ngOnDestroy(): void {
    this.closeDiscoveryStream();
  }

  // ── URL-based discovery ──────────────────────────────────────────────

  discoverLists(): void {
    const url = this.eventUrl().trim();
    if (!url || !/^https?:\/\//i.test(url)) {
      this.discoverUrlError.set('Please enter a valid URL starting with http:// or https://');
      return;
    }
    this.discoverUrlError.set(null);
    this.discoverError.set(null);
    this.closeDiscoveryStream();

    this.discoveredCards.set([]);
    this.missingSignals.set([]);
    this.discoveryRan.set(false);
    this.discoverTicker.set([]);
    this.discovering.set(true);

    this.audienceService.startDiscovery(url).subscribe({
      next: (res) => this.openDiscoveryStream(res.job_id),
      error: (err) => {
        this.discoverError.set(err?.message ?? 'Failed to start discovery');
        this.discovering.set(false);
      },
    });
  }

  private openDiscoveryStream(jobId: string): void {
    const es = new EventSource(this.audienceService.discoverStreamUrl(jobId));
    this.eventSource = es;

    es.onmessage = (evt: MessageEvent<string>) => {
      let msg: DiscoveryStreamEvent;
      try {
        msg = JSON.parse(evt.data);
      } catch {
        return;
      }

      if (msg.type === 'output') {
        this.discoverTicker.update((lines) => [...lines, msg.text]);
      } else if (msg.type === 'discovered') {
        const found = (msg.lists ?? []).map((l) => ({ ...l }));
        const uncertain = (msg.uncertain ?? []).map((l) => ({ ...l, signal: 'uncertain' }));
        this.discoveredCards.set([...found, ...uncertain]);
        this.missingSignals.set(msg.missing_signals ?? []);
        this.discoveryRan.set(true);

        // Auto-populate the manual brand/event inputs from what discovery
        // resolved, then run the same context loads loadContext() does —
        // suppression lists, last-sent emails, existing master lists.
        this.brandShort.set(msg.brand_short ?? '');
        this.eventName.set(msg.event_name ?? '');
        this.loadContext();
      }

      if (msg.done) {
        this.closeDiscoveryStream();
        this.discovering.set(false);
        if (msg.type === 'discovered' && msg.success === false && this.discoveredCards().length === 0) {
          this.discoverError.set('Discovery finished without finding any lists — see the log above.');
        }
      }
    };

    es.onerror = () => {
      this.closeDiscoveryStream();
      this.discovering.set(false);
    };
  }

  private closeDiscoveryStream(): void {
    if (this.eventSource) {
      this.eventSource.close();
      this.eventSource = null;
    }
  }

  /** Groups discoveredCards() by signal, in SIGNAL_ORDER, for the card grid. */
  discoverySections(): { signal: string; label: string; description: string; cards: DiscoveredList[] }[] {
    const bySignal = new Map<string, DiscoveredList[]>();
    for (const c of this.discoveredCards()) {
      const sig = c.signal || 'uncertain';
      const group = bySignal.get(sig);
      if (group) group.push(c);
      else bySignal.set(sig, [c]);
    }
    return SIGNAL_ORDER.filter((sig) => bySignal.has(sig)).map((sig) => ({
      signal: sig,
      label: SIGNAL_LABELS[sig] ?? sig,
      description: SIGNAL_DESC[sig] ?? '',
      cards: bySignal.get(sig)!,
    }));
  }

  /** Missing-signal entries for the "Qualifying lists not found" row — excludes event_speakers (own widget below). */
  missingSignalEntries(): { key: string; label: string; description: string }[] {
    return this.missingSignals()
      .filter((sig) => sig !== 'event_speakers')
      .map((sig) => ({ key: sig, ...(MISSING_SIGNAL_INFO[sig] ?? { label: sig, description: '', prompt: () => '' }) }));
  }

  /** The discovered event_speakers card (if any) covering the given scope, for the read-only speaker-scope status widget. */
  speakerScopeStatus(scopeKey: string): DiscoveredList | undefined {
    return this.discoveredCards().find((c) => c.signal === 'event_speakers' && speakerCardCoversScope(c, scopeKey));
  }

  /**
   * Builds a natural-language request for the given missing signal and
   * emits it upward so the parent (EmailCreation) can pre-fill the Custom
   * Audience tab's request box and switch to it. Not a full inline build —
   * per the legacy screenshot's own copy, this only pre-fills the request.
   */
  requestCreateList(sig: string): void {
    const info = MISSING_SIGNAL_INFO[sig];
    if (!info) return;
    this.createListRequested.emit(info.prompt(this.eventUrl().trim()));
  }

  /** Same as requestCreateList, but for one of the 3 scoped event_speakers rows. */
  requestCreateSpeakerList(scopeKey: string): void {
    this.createListRequested.emit(speakerScopePrompt(this.eventUrl().trim(), scopeKey));
  }

  /**
   * Auto-selects discovered cards that were used in a past send, and
   * synthesizes a "Used In Past Sends" card for any past-send inclusion
   * list that didn't match one of the discovery signals at all (e.g. a
   * regional/demographic segment) — mirrors legacy's loadLastSent, so these
   * "common" lists don't require a manual "Use same selection" click.
   */
  private autoSelectLastSentLists(): void {
    const includedIds = this.lastSentIncludedIds();
    if (includedIds.size === 0) return;

    const cards = this.discoveredCards();
    const cardIds = new Set(cards.map((c) => String(c.list_id)));
    const additions: DiscoveredList[] = [];
    const briefById = new Map<string, LastSentEmail['included_lists'][number]>();
    for (const e of this.lastSentEmails()) {
      for (const l of e.included_lists ?? []) {
        if (!briefById.has(l.list_id)) briefById.set(l.list_id, l);
      }
    }
    for (const [id, l] of briefById) {
      if (l.missing || cardIds.has(id)) continue;
      additions.push({
        list_id: id,
        name: l.name,
        signal: 'last_sent',
        size: l.size,
        reason: 'Used in a past send for this event; not classified under the signals above.',
      });
    }
    if (additions.length > 0) this.discoveredCards.set([...cards, ...additions]);

    const toSelect = [...cardIds, ...additions.map((a) => String(a.list_id))].filter((id) => includedIds.has(id));
    const nameById = new Map(
      [...cards, ...additions].map((c) => [String(c.list_id), c.name] as const),
    );
    this.selected.update((sel) => {
      const existing = new Set(sel.map((s) => s.id));
      const more = toSelect.filter((id) => !existing.has(id)).map((id) => ({ id, name: nameById.get(id) ?? id }));
      return more.length > 0 ? [...sel, ...more] : sel;
    });
  }

  /** Every list_id used by any past send for this event — drives the "Used last time" card badge. */
  lastSentIncludedIds(): Set<string> {
    const ids = new Set<string>();
    for (const e of this.lastSentEmails()) {
      for (const l of e.included_lists ?? []) ids.add(l.list_id);
    }
    return ids;
  }

  isSelectedId(id: string): boolean {
    return this.selected().some((s) => s.id === id);
  }

  /** Toggles a discovered card into/out of the same `selected` set the manual search-and-add flow uses, so preview/compose act on the combined set. */
  toggleDiscoveredCard(card: DiscoveredList): void {
    const id = String(card.list_id);
    if (this.isSelectedId(id)) this.removeFromAudience(id);
    else this.selected.update((s) => [...s, { id, name: card.name }]);
  }

  selectAllDiscovered(): void {
    const additions = this.discoveredCards()
      .filter((c) => !this.isSelectedId(String(c.list_id)))
      .map((c) => ({ id: String(c.list_id), name: c.name }));
    this.selected.update((s) => [...s, ...additions]);
  }

  clearDiscovered(): void {
    const ids = new Set(this.discoveredCards().map((c) => String(c.list_id)));
    this.selected.update((s) => s.filter((l) => !ids.has(l.id)));
  }

  // ── Discovered-lists stat row ────────────────────────────────────────

  /** Number of discovered segments (cards) — mirrors legacy's ab-stat-segments. */
  discoveredSegmentsCount(): number {
    return this.discoveredCards().length;
  }

  /** Sum of .size across currently-selected discovered cards — an estimate since sizes can overlap across lists. */
  discoveredContactsEstimate(): number {
    const selectedIds = new Set(this.selected().map((s) => s.id));
    return this.discoveredCards().reduce(
      (sum, c) => (selectedIds.has(String(c.list_id)) && typeof c.size === 'number' ? sum + c.size : sum),
      0,
    );
  }

  loadContext(): void {
    const brandShort = this.brandShort().trim();
    const eventName = this.eventName().trim();
    this.contextLoaded.set(true);

    this.suppressionLoading.set(true);
    this.suppressionError.set(null);
    this.audienceService.suppressionLists(brandShort, eventName).subscribe({
      next: (res) => {
        this.suppressionLists.set(res.results ?? []);
        this.suppressionLoading.set(false);
      },
      error: (err) => {
        this.suppressionError.set(err?.message ?? 'Failed to load suppression lists');
        this.suppressionLoading.set(false);
      },
    });

    this.lastSentLoading.set(true);
    this.lastSentError.set(null);
    this.audienceService.lastSent(eventName, brandShort).subscribe({
      next: (res) => {
        this.lastSentEmails.set(res.results ?? []);
        this.lastSentLoading.set(false);
        this.autoSelectLastSentLists();
      },
      error: (err) => {
        this.lastSentError.set(err?.message ?? 'Failed to load last-sent emails');
        this.lastSentLoading.set(false);
      },
    });

    this.existingLoading.set(true);
    this.existingError.set(null);
    this.audienceService.existingMasterLists(brandShort, eventName).subscribe({
      next: (res) => {
        this.existingMasterLists.set(res.results ?? []);
        this.existingLoading.set(false);
      },
      error: (err) => {
        this.existingError.set(err?.message ?? 'Failed to load existing master lists');
        this.existingLoading.set(false);
      },
    });
  }

  search(): void {
    const q = this.searchQuery().trim();
    if (!q) {
      this.searchResults.set([]);
      return;
    }
    this.searching.set(true);
    this.searchError.set(null);
    this.listsService.searchLists(q).subscribe({
      next: (res) => {
        this.searchResults.set(res.results ?? []);
        this.searching.set(false);
      },
      error: (err) => {
        this.searchError.set(err?.message ?? 'Search failed');
        this.searching.set(false);
      },
    });
  }

  isSelected(list: AudienceListInfo): boolean {
    return this.selected().some((s) => s.id === list.id);
  }

  toggleAudience(list: AudienceListInfo): void {
    if (this.isSelected(list)) this.removeFromAudience(list.id);
    else this.selected.update((s) => [...s, { id: list.id, name: list.name }]);
  }

  removeFromAudience(id: string): void {
    this.selected.update((s) => s.filter((l) => l.id !== id));
  }

  /** Reuses a previously-sent email's exact selection — both its inclusion lists AND its suppression lists, in one action. */
  useLastSentSelection(email: LastSentEmail): void {
    const additions = (email.included_lists ?? [])
      .filter((l) => !this.selected().some((s) => s.id === l.list_id))
      .map((l) => ({ id: l.list_id, name: l.name }));
    this.selected.update((s) => [...s, ...additions]);

    const ids = new Set(this.excludedListIds());
    for (const l of email.suppression_lists ?? []) ids.add(l.list_id);
    this.excludedListIds.set(ids);
  }

  toggleSuppression(list: SuppressionList): void {
    const ids = new Set(this.excludedListIds());
    if (ids.has(list.list_id)) ids.delete(list.list_id);
    else ids.add(list.list_id);
    this.excludedListIds.set(ids);
  }

  isSuppressionChecked(list: SuppressionList): boolean {
    return this.excludedListIds().has(list.list_id);
  }

  // ── Suppression & Exclusions grouping + stat row ─────────────────────

  /** Groups suppressionLists() by category, in rank order, with a section label per category. */
  suppressionSections(): { category: string; label: string; lists: SuppressionList[] }[] {
    const byCategory = new Map<string, SuppressionList[]>();
    for (const s of this.suppressionLists()) {
      const cat = s.category || 'standard';
      const group = byCategory.get(cat);
      if (group) group.push(s);
      else byCategory.set(cat, [s]);
    }
    return [...byCategory.keys()]
      .sort((a, b) => (SUPPRESSION_CATEGORY_RANK[a] ?? 9) - (SUPPRESSION_CATEGORY_RANK[b] ?? 9))
      .map((cat) => ({
        category: cat,
        label: SUPPRESSION_CATEGORY_LABELS[cat] ?? cat,
        lists: byCategory.get(cat)!,
      }));
  }

  /** Sum of .size across currently-checked suppression lists — an estimate since sizes can overlap across lists. */
  suppressionContactsEstimate(): number {
    const excluded = this.excludedListIds();
    return this.suppressionLists().reduce(
      (sum, s) => (excluded.has(s.list_id) && typeof s.size === 'number' ? sum + s.size : sum),
      0,
    );
  }

  previewSuppressionCount(): void {
    const ids = [...this.excludedListIds()];
    if (ids.length === 0) return;
    this.suppressionExactLoading.set(true);
    this.suppressionExactError.set(null);
    this.audienceService.previewCount({ list_ids: ids }).subscribe({
      next: (res) => {
        this.suppressionExactResult.set(res);
        this.suppressionExactLoading.set(false);
      },
      error: (err) => {
        this.suppressionExactError.set(err?.message ?? 'Preview failed');
        this.suppressionExactLoading.set(false);
      },
    });
  }

  previewCount(): void {
    const ids = this.selected().map((s) => s.id);
    if (ids.length === 0) return;
    this.previewLoading.set(true);
    this.previewError.set(null);
    this.audienceService.previewCount({ list_ids: ids }).subscribe({
      next: (res) => {
        this.previewResult.set(res);
        this.previewLoading.set(false);
      },
      error: (err) => {
        this.previewError.set(err?.message ?? 'Preview failed');
        this.previewLoading.set(false);
      },
    });
  }

  composeMaster(): void {
    const ids = this.selected().map((s) => s.id);
    if (ids.length === 0) return;
    this.composeLoading.set(true);
    this.composeError.set(null);
    this.qaResult.set(null);
    this.audienceService
      .composeMaster({
        list_ids: ids,
        name: this.masterListName().trim() || undefined,
        brand_short: this.brandShort().trim() || undefined,
        event_name: this.eventName().trim() || undefined,
        exclude_list_ids: [...this.excludedListIds()],
      })
      .subscribe({
        next: (res) => {
          this.composeResult.set(res);
          this.composeLoading.set(false);
        },
        error: (err) => {
          this.composeError.set(err?.message ?? 'Compose failed');
          this.composeLoading.set(false);
        },
      });
  }

  runQa(): void {
    const listId = this.composeResult()?.list_id;
    if (!listId) return;
    this.qaLoading.set(true);
    this.qaError.set(null);
    this.audienceService
      .qaRun({ list_ref: listId, targets_eu: this.targetsEU(), targets_ca: this.targetsCA() })
      .subscribe({
        next: (res) => {
          if (res.needs_disambiguation) {
            this.qaError.set('Ambiguous list reference — unexpected for a freshly-composed list ID');
          } else {
            this.qaResult.set(res);
          }
          this.qaLoading.set(false);
        },
        error: (err) => {
          this.qaError.set(err?.message ?? 'QA run failed');
          this.qaLoading.set(false);
        },
      });
  }

  qaReportUrl(): string | null {
    const listId = this.composeResult()?.list_id;
    if (!listId) return null;
    return this.audienceService.qaReportUrl(listId, this.targetsEU(), this.targetsCA());
  }

  qaCheckEntries(): { key: string; value: QaResultResponse['checks'][string] }[] {
    const checks = this.qaResult()?.checks ?? {};
    return Object.entries(checks).map(([key, value]) => ({ key, value }));
  }
}
