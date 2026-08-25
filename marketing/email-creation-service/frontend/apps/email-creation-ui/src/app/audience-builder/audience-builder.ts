import { Component, ElementRef, OnDestroy, ViewChild, effect, signal } from '@angular/core';
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

// Missing-signal descriptions for the "Qualifying lists not found" section
// (event_speakers is excluded — it gets its own always-on 3-row status
// widget below instead, see speakerScopeStatus()).
const MISSING_SIGNAL_INFO: Record<string, { label: string; description: string }> = {
  project_opt_in: {
    label: 'Project Opt-In',
    description: "Contacts opted into this project's own email subscription type (not the general LF newsletter).",
  },
  lf_newsletter_opt_in: {
    label: 'LF Newsletter Opt-In',
    description: 'Contacts opted into the Linux Foundation Newsletter subscription type.',
  },
  event_registration: {
    label: 'Event Registration',
    description: 'All-time registrants for this event, across all past editions.',
  },
  education_enrollment: {
    label: 'Education Enrollment',
    description: "Contacts enrolled in LFX Education courses related to this event's topic area.",
  },
  page_view: {
    label: 'Page View',
    description: "Contacts who viewed this event's page (page-view based segment).",
  },
};

const SPEAKER_SCOPES: { key: string; label: string }[] = [
  { key: 'current', label: 'Current event speakers' },
  { key: 'past', label: 'Past event speakers' },
  { key: 'current_past', label: 'Current + Past event speakers' },
];

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
      .map((sig) => ({ key: sig, ...(MISSING_SIGNAL_INFO[sig] ?? { label: sig, description: '' }) }));
  }

  /** The discovered event_speakers card (if any) covering the given scope, for the read-only speaker-scope status widget. */
  speakerScopeStatus(scopeKey: string): DiscoveredList | undefined {
    return this.discoveredCards().find((c) => c.signal === 'event_speakers' && speakerCardCoversScope(c, scopeKey));
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

  selectNoneDiscovered(): void {
    const ids = new Set(this.discoveredCards().map((c) => String(c.list_id)));
    this.selected.update((s) => s.filter((l) => !ids.has(l.id)));
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

  /** Populates the audience from a previously-sent email's included lists. */
  reuseIncludedLists(email: LastSentEmail): void {
    const additions = (email.included_lists ?? [])
      .filter((l) => !this.selected().some((s) => s.id === l.list_id))
      .map((l) => ({ id: l.list_id, name: l.name }));
    this.selected.update((s) => [...s, ...additions]);
  }

  /**
   * Explicit, separate action to check the suppression boxes this email
   * used last time — kept distinct from reuseIncludedLists so nothing gets
   * suppressed without the user seeing and choosing it here.
   */
  applyPastSuppressionSelection(email: LastSentEmail): void {
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
