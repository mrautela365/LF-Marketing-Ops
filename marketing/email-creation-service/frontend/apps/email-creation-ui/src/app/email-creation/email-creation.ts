import { Component, signal, type WritableSignal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import { DomSanitizer, type SafeHtml } from '@angular/platform-browser';
import type { AudienceStreamEvent, ContentSection, PlanResult } from '@email-creation/shared';
import { AudienceBuilder } from '../audience-builder/audience-builder';
import { EmailCreationService } from './email-creation.service';

type AudienceJobStatus = 'idle' | 'planning' | 'plan_ready' | 'building' | 'built' | 'error';

interface ChatEntry {
  who: 'you' | 'assistant';
  text: string;
}

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

  switchAudienceTab(tab: 'event' | 'custom' | 'reuse'): void {
    this.audienceSubTab.set(tab);
  }

  private openAudienceStream(
    jobId: string,
    ticker: WritableSignal<string[]>,
    status: WritableSignal<AudienceJobStatus>,
    onComplete: (ev: Extract<AudienceStreamEvent, { type: 'complete' }>) => void,
  ): EventSource {
    return this.service.openAudienceStream(jobId, this.sessionId(), (ev) => {
      if (ev.type === 'output' || ev.type === 'delta') {
        ticker.update((lines) => [...lines, ev.text]);
      } else if (ev.type === 'complete') {
        onComplete(ev);
      } else if (ev.type === 'error') {
        ticker.update((lines) => [...lines, `⚠️ ${ev.text}`]);
        status.set('error');
      }
    });
  }

  runEventAudiencePlan(): void {
    const url = this.eventAudienceUrl().trim();
    if (!url) return;
    this.eventAudienceSource?.close();
    this.eventAudienceTicker.set([]);
    this.eventAudiencePlanText.set('');
    this.eventAudienceError.set(null);
    this.eventAudienceStatus.set('planning');
    this.service.audiencePlan({ session_id: this.sessionId() ?? undefined, event_url: url }).subscribe({
      next: (res) => {
        this.eventAudienceSource = this.openAudienceStream(res.job_id, this.eventAudienceTicker, this.eventAudienceStatus, () => {
          this.eventAudiencePlanText.set(this.eventAudienceTicker().join('\n'));
          this.eventAudienceStatus.set('plan_ready');
        });
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
    this.service.buildAudience({ session_id: this.sessionId() ?? undefined, event_url: url, plan }).subscribe({
      next: (res) => {
        this.eventAudienceSource = this.openAudienceStream(res.job_id, this.eventAudienceTicker, this.eventAudienceStatus, (ev) => {
          this.eventAudienceStatus.set('built');
          if (ev.master_list_id) {
            this.masterListId.set(ev.master_list_id);
            this.masterListUrl.set(ev.master_list_url ?? null);
            this.sendListIdsText.set(ev.master_list_id);
          }
        });
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
  }

  runCustomAudiencePlan(): void {
    const request = this.customAudienceRequest().trim();
    if (!request) return;
    this.customAudienceSource?.close();
    this.customAudienceTicker.set([]);
    this.customAudiencePlanText.set('');
    this.customAudienceError.set(null);
    this.customAudienceStatus.set('planning');
    this.service.customAudiencePlan({ request }).subscribe({
      next: (res) => {
        this.customAudienceSource = this.openAudienceStream(res.job_id, this.customAudienceTicker, this.customAudienceStatus, () => {
          this.customAudiencePlanText.set(this.customAudienceTicker().join('\n'));
          this.customAudienceStatus.set('plan_ready');
        });
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
    this.service.customAudienceRun({ request, plan }).subscribe({
      next: (res) => {
        this.customAudienceSource = this.openAudienceStream(res.job_id, this.customAudienceTicker, this.customAudienceStatus, (ev) => {
          this.customAudienceStatus.set('built');
          if (ev.master_list_id) {
            this.masterListId.set(ev.master_list_id);
            this.masterListUrl.set(ev.master_list_url ?? null);
            this.sendListIdsText.set(ev.master_list_id);
          }
        });
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

          const listIds = this.parseSendListIds();
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
