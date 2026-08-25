import { Component, signal, type WritableSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import type {
  AudienceListInfo,
  AudienceQuestion,
  AudienceStreamEvent,
  ContentSection,
  PlanResult,
} from '@email-creation/shared';
import { AudienceBuilder } from '../audience-builder/audience-builder';
import { ListsService } from '../lists.service';
import { EmailCreationService } from './email-creation.service';

type AudienceJobStatus = 'idle' | 'planning' | 'plan_ready' | 'building' | 'built' | 'error';
type RoleSpeakerScope = 'current' | 'past' | 'current_past';

interface ChatEntry {
  who: 'you' | 'assistant';
  text: string;
}

interface ExtraFilter {
  property: string;
  operator: string;
  value: string;
}

interface SubListEntry {
  name: string;
  id: string;
  url: string;
  kind: 'created' | 'master' | 'selected';
}

const ROLE_SPEAKER_SCOPE_TAGS: Record<RoleSpeakerScope, string> = {
  current: 'Current',
  past: 'Past',
  current_past: 'Current + Past',
};

const EXTRA_FILTER_NO_VALUE_OPS = new Set(['is known', 'is unknown']);

/**
 * Ports the legacy 4-step email-creation wizard (frontend/app.js Steps 1-2-4;
 * Step 3 "Audience Preview" is intentionally simplified here to a plain
 * send-list-id field — the full audience-selection UX already lives in the
 * ported Audience Builder tab). Talks to the legacy Python backend's LLM
 * routes directly (proxied at /api/plan-start, /api/generate-content, etc. —
 * see proxy.conf.json) since the Go LLM gateway (migration phase 4) doesn't
 * exist yet.
 */
@Component({
  selector: 'app-email-creation',
  imports: [FormsModule, AudienceBuilder],
  templateUrl: './email-creation.html',
  styleUrl: './email-creation.scss',
})
export class EmailCreation {
  protected readonly step = signal<1 | 2 | 3 | 4>(1);

  // Step 1 — campaign brief.
  protected readonly eventUrl = signal('');
  protected readonly emailType = signal('');
  protected readonly extraContext = signal('');
  protected readonly planError = signal<string | null>(null);

  // Live brief (shared across steps 1-2 via one SSE token).
  protected readonly briefLines = signal<string[]>([]);
  protected readonly briefStatus = signal<'idle' | 'live' | 'done' | 'error'>('idle');
  private briefSource: EventSource | null = null;
  private progressToken = '';

  protected readonly sessionId = signal<string | null>(null);
  protected readonly planResult = signal<PlanResult | null>(null);

  // Step 2 — generated content.
  protected readonly contentLoading = signal(false);
  protected readonly contentError = signal<string | null>(null);
  protected readonly generatedSubject = signal('');
  protected readonly generatedPreview = signal('');
  protected readonly generatedHtml = signal('');
  protected readonly sections = signal<ContentSection[]>([]);
  protected readonly variantASubject = signal('');
  protected readonly variantAPreview = signal('');
  protected readonly variantAHtml = signal('');
  protected readonly refineText = signal('');
  protected readonly chat2 = signal<ChatEntry[]>([]);
  protected readonly chat2Input = signal('');

  // Step 3 — Audience Preview.
  protected readonly audienceSubTab = signal<'event' | 'custom' | 'reuse'>('event');
  protected readonly sendListIdsText = signal('');
  protected readonly masterListId = signal<string | null>(null);
  protected readonly masterListUrl = signal<string | null>(null);

  // Step 3, "Event Audience" sub-tab.
  protected readonly eventAudienceUrl = signal('');
  protected readonly eventAudienceTicker = signal<string[]>([]);
  protected readonly eventAudienceStatus = signal<AudienceJobStatus>('idle');
  protected readonly eventAudiencePlanText = signal('');
  protected readonly eventAudienceError = signal<string | null>(null);
  private eventAudienceSource: EventSource | null = null;

  // Step 3, "Custom Audience" sub-tab.
  protected readonly customAudienceRequest = signal('');
  protected readonly customAudienceTicker = signal<string[]>([]);
  protected readonly customAudienceStatus = signal<AudienceJobStatus>('idle');
  protected readonly customAudiencePlanText = signal('');
  protected readonly customAudienceError = signal<string | null>(null);
  private customAudienceSource: EventSource | null = null;

  // Step 3 — lists rolled into whichever audience is currently being planned/built
  // (event or custom — only one flow is "live" at a time, matching legacy _subLists).
  protected readonly subLists = signal<SubListEntry[]>([]);

  // Step 3 — accumulated "Q: ...\nA: ..." text from answered clarifying questions,
  // folded into the next plan request so the agent doesn't ask again.
  protected readonly audienceQA = signal('');
  protected readonly pendingQuestions = signal<AudienceQuestion[] | null>(null);
  protected readonly pendingQuestionsFlow = signal<'event' | 'custom'>('event');
  protected readonly questionAnswers = signal<string[]>([]);

  // Step 3, Event tab — "add more filters" + "restrict to a role" plan-review panels.
  protected readonly eventExtraFilters = signal<ExtraFilter[]>([]);
  protected readonly eventExtraFilterProperty = signal('');
  protected readonly eventExtraFilterOperator = signal('is equal to');
  protected readonly eventExtraFilterValue = signal('');
  protected readonly eventRoleSpeakers = signal(false);
  protected readonly eventRoleSpeakerScope = signal<RoleSpeakerScope>('current_past');
  protected readonly eventRoleAmbassadors = signal(false);

  // Step 3, Custom tab — same panels, independent state.
  protected readonly customExtraFilters = signal<ExtraFilter[]>([]);
  protected readonly customExtraFilterProperty = signal('');
  protected readonly customExtraFilterOperator = signal('is equal to');
  protected readonly customExtraFilterValue = signal('');
  protected readonly customRoleSpeakers = signal(false);
  protected readonly customRoleSpeakerScope = signal<RoleSpeakerScope>('current_past');
  protected readonly customRoleAmbassadors = signal(false);

  // Step 3 — "Or use an existing list" manual picker (distinct from the Reuse tab's
  // full AudienceBuilder search): picks an existing HubSpot list as the send list directly.
  protected readonly listSearchQuery = signal('');
  protected readonly listSearchResults = signal<AudienceListInfo[]>([]);
  protected readonly selectedExistingList = signal<{ id: string; name: string; size?: number } | null>(null);
  private listSearchTimer: ReturnType<typeof setTimeout> | null = null;

  // Step 4 — implementation.
  protected readonly cloneLoading = signal(false);
  protected readonly cloneError = signal<string | null>(null);
  protected readonly emailId = signal<string | null>(null);
  protected readonly draftUrl = signal<string | null>(null);
  protected readonly variantADraftUrl = signal<string | null>(null);
  protected readonly variantBDraftUrl = signal<string | null>(null);
  protected readonly sendListStatus = signal<string | null>(null);
  protected readonly sendListError = signal<string | null>(null);
  protected readonly chat4 = signal<ChatEntry[]>([]);
  protected readonly chat4Input = signal('');

  constructor(
    private readonly service: EmailCreationService,
    private readonly listsService: ListsService,
    private readonly sanitizer: DomSanitizer,
  ) {}

  sectionLabel(section: ContentSection): string {
    return section.type === 'button' ? 'Button' : 'Text block';
  }

  sanitizedSectionHtml(section: ContentSection): SafeHtml {
    return this.sanitizer.bypassSecurityTrustHtml(section.html || '');
  }

  private newToken(): string {
    return `tok-${Math.random().toString(36).slice(2)}${Date.now()}`;
  }

  private openBrief(token: string, onPlanDone: (result: PlanResult) => void): void {
    this.briefSource?.close();
    this.briefLines.set([]);
    this.briefStatus.set('live');
    this.briefSource = this.service.openProgressStream(token, (ev) => {
      if (ev.type === 'heartbeat') return;
      if (ev.type === 'brief') {
        this.briefLines.update((lines) => [...lines, ev.text]);
        if (ev.error) this.briefStatus.set('error');
      } else if (ev.type === 'plan_done') {
        this.briefStatus.set('done');
        onPlanDone(ev.result);
      } else if (ev.type === 'error') {
        this.briefLines.update((lines) => [...lines, `⚠️ ${ev.text}`]);
        this.briefStatus.set('error');
      }
    });
  }

  generatePlan(): void {
    const url = this.eventUrl().trim();
    if (!url) return;
    this.planError.set(null);
    const token = this.newToken();
    this.progressToken = token;
    this.step.set(2);
    this.openBrief(token, (result) => {
      this.sessionId.set(result.session_id);
      this.planResult.set(result);
      this.generateContent('', token);
    });

    this.service
      .planStart({
        url,
        extra_context: this.extraContext().trim() || undefined,
        email_type: this.emailType().trim() || undefined,
        progress_token: token,
      })
      .subscribe({
        error: (err) => {
          this.planError.set(err?.message ?? 'Failed to start plan');
          this.briefStatus.set('error');
        },
      });
  }

  private generateContent(changeRequest: string, token: string): void {
    const sessionId = this.sessionId();
    if (!sessionId) return;
    this.contentLoading.set(true);
    this.contentError.set(null);
    this.service
      .generateContent({ session_id: sessionId, change_request: changeRequest || undefined, progress_token: token })
      .subscribe({
        next: (res) => {
          this.generatedSubject.set(res.generated_subject);
          this.generatedPreview.set(res.generated_preview);
          this.generatedHtml.set(res.generated_html);
          this.sections.set(res.sections ?? []);
          this.variantASubject.set(res.variant_a_subject);
          this.variantAPreview.set(res.variant_a_preview);
          this.variantAHtml.set(res.variant_a_html);
          this.contentLoading.set(false);
        },
        error: (err) => {
          this.contentError.set(err?.message ?? 'Content generation failed');
          this.contentLoading.set(false);
        },
      });
  }

  removeSection(index: number): void {
    const sessionId = this.sessionId();
    if (!sessionId) return;
    const next = this.sections().filter((_, i) => i !== index);
    this.sections.set(next);
    this.service.updateSections({ session_id: sessionId, sections: next }).subscribe({
      next: (res) => this.generatedHtml.set(res.generated_html),
    });
  }

  requestContentChanges(): void {
    const text = this.refineText().trim();
    if (!text) return;
    const token = this.newToken();
    this.progressToken = token;
    this.openBrief(token, () => {});
    this.generateContent(text, token);
    this.refineText.set('');
  }

  goToAudience(): void {
    this.step.set(3);
    if (!this.eventAudienceUrl().trim()) {
      this.eventAudienceUrl.set(this.eventUrl());
    }
  }

  editPlan(): void {
    this.step.set(1);
  }

  private parseSendListIds(): string[] {
    return this.sendListIdsText()
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean);
  }

  // Mirrors legacy startImplementation's `_masterListIds.length ? _masterListIds
  // : _masterListId ? [_masterListId] : []` — the manual field is an override,
  // the built/selected master list is the fallback.
  private resolveSendListIds(): string[] {
    const manual = this.parseSendListIds();
    if (manual.length) return manual;
    const masterId = this.masterListId();
    return masterId ? [masterId] : [];
  }

  switchAudienceTab(tab: 'event' | 'custom' | 'reuse'): void {
    this.audienceSubTab.set(tab);
  }

  /** Pre-fills the Custom Audience tab's request box from a "Create list" click in the Reuse/Discover tab, then switches to it. */
  onAudienceBuilderCreateListRequested(promptText: string): void {
    this.customAudienceRequest.set(promptText);
    this.switchAudienceTab('custom');
  }

  private openAudienceStream(
    jobId: string,
    ticker: WritableSignal<string[]>,
    status: WritableSignal<AudienceJobStatus>,
    onQuestion: (questions: AudienceQuestion[]) => void,
    onComplete: (ev: Extract<AudienceStreamEvent, { type: 'complete' }>) => void,
  ): EventSource {
    // Deltas arrive as arbitrary text fragments, not whole lines — buffer them so
    // parseSubList's regex only ever sees complete lines (mirrors legacy _openAudienceStream).
    let lineBuf = '';
    const flushLine = (line: string) => {
      if (line.trim()) this.parseSubList(line);
    };
    return this.service.openAudienceStream(jobId, this.sessionId(), (ev) => {
      if (ev.type === 'output') {
        ticker.update((lines) => [...lines, ev.text]);
        if (ev.delta) {
          lineBuf += ev.text;
          let idx: number;
          while ((idx = lineBuf.indexOf('\n')) !== -1) {
            flushLine(lineBuf.slice(0, idx));
            lineBuf = lineBuf.slice(idx + 1);
          }
        } else {
          flushLine(ev.text);
        }
      } else if (ev.type === 'question') {
        onQuestion(ev.questions);
      } else if (ev.type === 'complete') {
        if (lineBuf.trim()) flushLine(lineBuf);
        onComplete(ev);
      } else if (ev.type === 'error') {
        ticker.update((lines) => [...lines, `⚠️ ${ev.text}`]);
        status.set('error');
      }
    });
  }

  private parseSubList(text: string): void {
    const match = text.match(/(?:✅|🔁)\s*(.+?)\s+(?:created|updated in place)\s*[—\-:]+\s*ID:?\s*(\d{3,})(?:\s*[—\-]+\s*(\S+))?/i);
    if (!match) return;
    const name = match[1].trim().replace(/^\[|\]$/g, '');
    const id = match[2];
    const url = match[3] ?? '';
    const existing = this.subLists().find((s) => s.id === id);
    if (existing) {
      if (url) this.subLists.update((list) => list.map((s) => (s.id === id ? { ...s, url } : s)));
      return;
    }
    this.subLists.update((list) => [...list, { name, id, url, kind: 'created' }]);
  }

  private markMaster(id: string, url: string | undefined): void {
    const idStr = String(id);
    const found = this.subLists().some((s) => s.id === idStr);
    if (found) {
      this.subLists.update((list) => list.map((s) => (s.id === idStr ? { ...s, kind: 'master', url: url || s.url } : s)));
    } else {
      this.subLists.update((list) => [...list, { name: 'Master Audience', id: idStr, url: url ?? '', kind: 'master' }]);
    }
  }

  private extraFiltersPlanText(filters: ExtraFilter[]): string {
    if (!filters.length) return '';
    const lines = filters.map((f) => `- Property "${f.property}" ${f.operator}${f.value ? ` "${f.value}"` : ''}`);
    return `\n\n## USER-ADDED FILTERS\n${lines.join('\n')}\n`;
  }

  private roleFiltersPlanText(speakers: boolean, speakerScope: RoleSpeakerScope, ambassadors: boolean): string {
    const lines: string[] = [];
    if (speakers) lines.push(`- Event speakers only (SPEAKER SCOPE: ${ROLE_SPEAKER_SCOPE_TAGS[speakerScope]})`);
    if (ambassadors) lines.push('- Community ambassadors only');
    return lines.length ? `\n\n## ROLE FILTERS\n${lines.join('\n')}\n` : '';
  }

  extraFilterValueDisabled(tab: 'event' | 'custom'): boolean {
    const operator = tab === 'event' ? this.eventExtraFilterOperator() : this.customExtraFilterOperator();
    return EXTRA_FILTER_NO_VALUE_OPS.has(operator);
  }

  addExtraFilter(tab: 'event' | 'custom'): void {
    const propertySignal = tab === 'event' ? this.eventExtraFilterProperty : this.customExtraFilterProperty;
    const operatorSignal = tab === 'event' ? this.eventExtraFilterOperator : this.customExtraFilterOperator;
    const valueSignal = tab === 'event' ? this.eventExtraFilterValue : this.customExtraFilterValue;
    const filtersSignal = tab === 'event' ? this.eventExtraFilters : this.customExtraFilters;
    const errorSignal = tab === 'event' ? this.eventAudienceError : this.customAudienceError;

    const property = propertySignal().trim();
    const operator = operatorSignal();
    const needsValue = !EXTRA_FILTER_NO_VALUE_OPS.has(operator);
    const value = needsValue ? valueSignal().trim() : '';

    if (!property) {
      errorSignal.set('Enter a property name for the filter.');
      return;
    }
    if (needsValue && !value) {
      errorSignal.set("Enter a value for this filter, or pick 'is known'/'is unknown'.");
      return;
    }
    errorSignal.set(null);
    filtersSignal.update((filters) => [...filters, { property, operator, value }]);
    propertySignal.set('');
    valueSignal.set('');
  }

  removeExtraFilter(tab: 'event' | 'custom', index: number): void {
    const filtersSignal = tab === 'event' ? this.eventExtraFilters : this.customExtraFilters;
    filtersSignal.update((filters) => filters.filter((_, i) => i !== index));
  }

  answerQuestion(index: number, value: string): void {
    this.questionAnswers.update((answers) => {
      const next = [...answers];
      next[index] = value;
      return next;
    });
  }

  allQuestionsAnswered(): boolean {
    const questions = this.pendingQuestions();
    if (!questions) return false;
    const answers = this.questionAnswers();
    return questions.every((_, i) => !!answers[i]?.trim());
  }

  submitQuestionAnswers(): void {
    const questions = this.pendingQuestions();
    if (!questions || !this.allQuestionsAnswered()) return;
    const answers = this.questionAnswers();
    const qaBlock = questions.map((q, i) => `Q: ${q.question}\nA: ${answers[i]}`).join('\n');
    this.audienceQA.set(this.audienceQA() ? `${this.audienceQA()}\n${qaBlock}` : qaBlock);
    const flow = this.pendingQuestionsFlow();
    this.pendingQuestions.set(null);
    this.questionAnswers.set([]);
    if (flow === 'custom') this.runCustomAudiencePlan();
    else this.runEventAudiencePlan();
  }

  discardQuestions(): void {
    this.pendingQuestions.set(null);
    this.questionAnswers.set([]);
  }

  onListSearch(query: string): void {
    this.listSearchQuery.set(query);
    if (this.listSearchTimer) clearTimeout(this.listSearchTimer);
    if (!query || query.length < 2) {
      this.listSearchResults.set([]);
      return;
    }
    this.listSearchTimer = setTimeout(() => {
      this.listsService.searchLists(query).subscribe({
        next: (res) => this.listSearchResults.set(res.results ?? []),
        error: () => this.listSearchResults.set([]),
      });
    }, 300);
  }

  selectExistingList(list: AudienceListInfo): void {
    this.listSearchQuery.set('');
    this.listSearchResults.set([]);
    this.selectedExistingList.set({ id: list.id, name: list.name, size: list.size });
    this.masterListId.set(list.id);
    this.masterListUrl.set(null);
    this.sendListIdsText.set(list.id);
    this.subLists.set([{ name: list.name, id: list.id, url: '', kind: 'selected' }]);
  }

  clearExistingList(): void {
    const subs = this.subLists();
    this.selectedExistingList.set(null);
    this.listSearchQuery.set('');
    this.listSearchResults.set([]);
    if (subs.length === 1 && subs[0].kind === 'selected') {
      this.masterListId.set(null);
      this.masterListUrl.set(null);
      this.sendListIdsText.set('');
      this.subLists.set([]);
    }
  }

  runEventAudiencePlan(): void {
    const url = this.eventAudienceUrl().trim();
    if (!url) return;
    this.eventAudienceSource?.close();
    this.eventAudienceTicker.set([]);
    this.eventAudiencePlanText.set('');
    this.eventAudienceError.set(null);
    this.eventAudienceStatus.set('planning');
    this.subLists.set([]);
    this.selectedExistingList.set(null);
    this.masterListId.set(null);
    this.masterListUrl.set(null);
    this.pendingQuestions.set(null);
    this.questionAnswers.set([]);
    this.service
      .audiencePlan({ session_id: this.sessionId() ?? undefined, event_url: url, qa: this.audienceQA() || undefined })
      .subscribe({
        next: (res) => {
          this.eventAudienceSource = this.openAudienceStream(
            res.job_id,
            this.eventAudienceTicker,
            this.eventAudienceStatus,
            (questions) => {
              this.pendingQuestionsFlow.set('event');
              this.pendingQuestions.set(questions);
              this.questionAnswers.set(questions.map(() => ''));
            },
            () => {
              this.eventAudiencePlanText.set(this.eventAudienceTicker().join('\n'));
              this.eventAudienceStatus.set('plan_ready');
            },
          );
        },
        error: (err) => {
          this.eventAudienceError.set(err?.message ?? 'Failed to start audience plan');
          this.eventAudienceStatus.set('error');
        },
      });
  }

  approveEventAudiencePlan(): void {
    const url = this.eventAudienceUrl().trim();
    const plan = this.eventAudiencePlanText().trim();
    if (!url || !plan) return;
    this.eventAudienceSource?.close();
    this.eventAudienceTicker.set([]);
    this.eventAudienceError.set(null);
    this.eventAudienceStatus.set('building');
    const planWithExtras =
      plan +
      this.extraFiltersPlanText(this.eventExtraFilters()) +
      this.roleFiltersPlanText(this.eventRoleSpeakers(), this.eventRoleSpeakerScope(), this.eventRoleAmbassadors());
    this.service
      .buildAudience({
        session_id: this.sessionId() ?? undefined,
        event_url: url,
        plan: planWithExtras,
        qa: this.audienceQA() || undefined,
      })
      .subscribe({
        next: (res) => {
          this.eventAudienceSource = this.openAudienceStream(
            res.job_id,
            this.eventAudienceTicker,
            this.eventAudienceStatus,
            (questions) => {
              this.pendingQuestionsFlow.set('event');
              this.pendingQuestions.set(questions);
              this.questionAnswers.set(questions.map(() => ''));
            },
            (ev) => {
              this.eventAudienceStatus.set('built');
              if (ev.master_list_id) {
                this.masterListId.set(ev.master_list_id);
                this.masterListUrl.set(ev.master_list_url ?? null);
                this.sendListIdsText.set(ev.master_list_id);
                this.markMaster(ev.master_list_id, ev.master_list_url);
              }
            },
          );
        },
        error: (err) => {
          this.eventAudienceError.set(err?.message ?? 'Failed to start audience build');
          this.eventAudienceStatus.set('error');
        },
      });
  }

  discardEventAudiencePlan(): void {
    this.eventAudienceSource?.close();
    this.eventAudienceSource = null;
    this.eventAudienceTicker.set([]);
    this.eventAudiencePlanText.set('');
    this.eventAudienceError.set(null);
    this.eventAudienceStatus.set('idle');
    this.eventExtraFilters.set([]);
    this.eventRoleSpeakers.set(false);
    this.eventRoleSpeakerScope.set('current_past');
    this.eventRoleAmbassadors.set(false);
    this.pendingQuestions.set(null);
    this.questionAnswers.set([]);
    this.subLists.set([]);
  }

  runCustomAudiencePlan(): void {
    const request = this.customAudienceRequest().trim();
    if (!request) return;
    this.customAudienceSource?.close();
    this.customAudienceTicker.set([]);
    this.customAudiencePlanText.set('');
    this.customAudienceError.set(null);
    this.customAudienceStatus.set('planning');
    this.subLists.set([]);
    this.selectedExistingList.set(null);
    this.masterListId.set(null);
    this.masterListUrl.set(null);
    this.pendingQuestions.set(null);
    this.questionAnswers.set([]);
    this.service.customAudiencePlan({ request, qa: this.audienceQA() || undefined }).subscribe({
      next: (res) => {
        this.customAudienceSource = this.openAudienceStream(
          res.job_id,
          this.customAudienceTicker,
          this.customAudienceStatus,
          (questions) => {
            this.pendingQuestionsFlow.set('custom');
            this.pendingQuestions.set(questions);
            this.questionAnswers.set(questions.map(() => ''));
          },
          () => {
            this.customAudiencePlanText.set(this.customAudienceTicker().join('\n'));
            this.customAudienceStatus.set('plan_ready');
          },
        );
      },
      error: (err) => {
        this.customAudienceError.set(err?.message ?? 'Failed to start audience plan');
        this.customAudienceStatus.set('error');
      },
    });
  }

  approveCustomAudiencePlan(): void {
    const request = this.customAudienceRequest().trim();
    const plan = this.customAudiencePlanText().trim();
    if (!request || !plan) return;
    this.customAudienceSource?.close();
    this.customAudienceTicker.set([]);
    this.customAudienceError.set(null);
    this.customAudienceStatus.set('building');
    const planWithExtras =
      plan +
      this.extraFiltersPlanText(this.customExtraFilters()) +
      this.roleFiltersPlanText(this.customRoleSpeakers(), this.customRoleSpeakerScope(), this.customRoleAmbassadors());
    this.service.customAudienceRun({ request, plan: planWithExtras, qa: this.audienceQA() || undefined }).subscribe({
      next: (res) => {
        this.customAudienceSource = this.openAudienceStream(
          res.job_id,
          this.customAudienceTicker,
          this.customAudienceStatus,
          (questions) => {
            this.pendingQuestionsFlow.set('custom');
            this.pendingQuestions.set(questions);
            this.questionAnswers.set(questions.map(() => ''));
          },
          (ev) => {
            this.customAudienceStatus.set('built');
            if (ev.master_list_id) {
              this.masterListId.set(ev.master_list_id);
              this.masterListUrl.set(ev.master_list_url ?? null);
              this.sendListIdsText.set(ev.master_list_id);
              this.markMaster(ev.master_list_id, ev.master_list_url);
            }
          },
        );
      },
      error: (err) => {
        this.customAudienceError.set(err?.message ?? 'Failed to start audience build');
        this.customAudienceStatus.set('error');
      },
    });
  }

  discardCustomAudiencePlan(): void {
    this.customAudienceSource?.close();
    this.customAudienceSource = null;
    this.customAudienceTicker.set([]);
    this.customAudiencePlanText.set('');
    this.customAudienceError.set(null);
    this.customAudienceStatus.set('idle');
    this.customExtraFilters.set([]);
    this.customRoleSpeakers.set(false);
    this.customRoleSpeakerScope.set('current_past');
    this.customRoleAmbassadors.set(false);
    this.pendingQuestions.set(null);
    this.questionAnswers.set([]);
    this.subLists.set([]);
  }

  skipAudience(): void {
    this.sendListIdsText.set('');
    this.masterListId.set(null);
    this.masterListUrl.set(null);
    this.startImplementation();
  }

  startImplementation(): void {
    const sessionId = this.sessionId();
    if (!sessionId) return;
    this.step.set(4);
    this.cloneLoading.set(true);
    this.cloneError.set(null);
    this.sendListStatus.set(null);
    this.sendListError.set(null);
    this.service
      .clone({
        session_id: sessionId,
        approved: true,
        subject: this.generatedSubject(),
        preview_text: this.generatedPreview(),
      })
      .subscribe({
        next: (res) => {
          this.emailId.set(res.email_id ?? null);
          this.draftUrl.set(res.draft_url ?? null);
          this.variantADraftUrl.set(res.variant_a_draft_url ?? res.draft_url ?? null);
          this.variantBDraftUrl.set(res.variant_b_draft_url ?? null);
          this.cloneLoading.set(false);

          const listIds = this.resolveSendListIds();
          if (listIds.length === 0 || !res.email_id) {
            this.sendListStatus.set(listIds.length === 0 ? 'No audience list attached.' : null);
            return;
          }
          this.service.setSendList({ session_id: sessionId, email_id: res.email_id, send_list_ids: listIds }).subscribe({
            next: (sl) => this.sendListStatus.set(`Send list applied: ${sl.send_list_id} (${sl.list_type ?? 'list'})`),
            error: (err) => this.sendListError.set(err?.message ?? 'Failed to apply send list'),
          });
        },
        error: (err) => {
          this.cloneError.set(err?.message ?? 'Clone failed');
          this.cloneLoading.set(false);
          this.step.set(3);
        },
      });
  }

  sendChat(which: 2 | 4): void {
    const sessionId = this.sessionId();
    const inputSignal = which === 2 ? this.chat2Input : this.chat4Input;
    const logSignal = which === 2 ? this.chat2 : this.chat4;
    const message = inputSignal().trim();
    if (!sessionId || !message) return;
    logSignal.update((log) => [...log, { who: 'you', text: message }]);
    inputSignal.set('');
    this.service.chat({ session_id: sessionId, message }).subscribe({
      next: (res) => logSignal.update((log) => [...log, { who: 'assistant', text: res.message }]),
      error: (err) => logSignal.update((log) => [...log, { who: 'assistant', text: `⚠️ ${err?.message ?? 'Chat failed'}` }]),
    });
  }

  startOver(): void {
    this.briefSource?.close();
    this.briefSource = null;
    this.eventAudienceSource?.close();
    this.eventAudienceSource = null;
    this.customAudienceSource?.close();
    this.customAudienceSource = null;
    this.step.set(1);
    this.eventUrl.set('');
    this.emailType.set('');
    this.extraContext.set('');
    this.planError.set(null);
    this.briefLines.set([]);
    this.briefStatus.set('idle');
    this.sessionId.set(null);
    this.planResult.set(null);
    this.generatedSubject.set('');
    this.generatedPreview.set('');
    this.generatedHtml.set('');
    this.sections.set([]);
    this.variantASubject.set('');
    this.variantAPreview.set('');
    this.variantAHtml.set('');
    this.refineText.set('');
    this.chat2.set([]);
    this.audienceSubTab.set('event');
    this.sendListIdsText.set('');
    this.masterListId.set(null);
    this.masterListUrl.set(null);
    this.eventAudienceUrl.set('');
    this.eventAudienceTicker.set([]);
    this.eventAudienceStatus.set('idle');
    this.eventAudiencePlanText.set('');
    this.eventAudienceError.set(null);
    this.subLists.set([]);
    this.audienceQA.set('');
    this.pendingQuestions.set(null);
    this.pendingQuestionsFlow.set('event');
    this.questionAnswers.set([]);
    this.eventExtraFilters.set([]);
    this.eventExtraFilterProperty.set('');
    this.eventExtraFilterOperator.set('is equal to');
    this.eventExtraFilterValue.set('');
    this.eventRoleSpeakers.set(false);
    this.eventRoleSpeakerScope.set('current_past');
    this.eventRoleAmbassadors.set(false);
    this.customExtraFilters.set([]);
    this.customExtraFilterProperty.set('');
    this.customExtraFilterOperator.set('is equal to');
    this.customExtraFilterValue.set('');
    this.customRoleSpeakers.set(false);
    this.customRoleSpeakerScope.set('current_past');
    this.customRoleAmbassadors.set(false);
    this.listSearchQuery.set('');
    this.listSearchResults.set([]);
    this.selectedExistingList.set(null);
    this.customAudienceRequest.set('');
    this.customAudienceTicker.set([]);
    this.customAudienceStatus.set('idle');
    this.customAudiencePlanText.set('');
    this.customAudienceError.set(null);
    this.emailId.set(null);
    this.draftUrl.set(null);
    this.variantADraftUrl.set(null);
    this.variantBDraftUrl.set(null);
    this.sendListStatus.set(null);
    this.sendListError.set(null);
    this.chat4.set([]);
  }
}
