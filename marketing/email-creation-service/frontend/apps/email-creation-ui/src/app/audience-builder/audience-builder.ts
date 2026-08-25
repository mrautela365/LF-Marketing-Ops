import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type {
  AudienceListInfo,
  ComposeMasterListResponse,
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

@Component({
  selector: 'app-audience-builder',
  imports: [FormsModule],
  templateUrl: './audience-builder.html',
  styleUrl: './audience-builder.scss',
})
export class AudienceBuilder {
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
  ) {}

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
