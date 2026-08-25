import { Component, signal } from '@angular/core';
import { FormsModule } from '@angular/forms';
import type { AudienceListInfo, StatusResponse } from '@email-creation/shared';
import { AudienceBuilder } from './audience-builder/audience-builder';
import { EmailCreation } from './email-creation/email-creation';
import { ListsService } from './lists.service';
import { StatusService } from './status.service';

@Component({
  selector: 'app-root',
  imports: [FormsModule, AudienceBuilder, EmailCreation],
  templateUrl: './app.html',
  styleUrl: './app.scss',
})
export class App {
  protected readonly title = signal('LF Email Automation');
  protected readonly subtitle = signal('Campaign Builder');
  protected readonly activeTab = signal<'status' | 'audience-builder' | 'email-creation'>('email-creation');

  protected readonly status = signal<StatusResponse | null>(null);
  protected readonly statusError = signal<string | null>(null);

  protected readonly query = signal('');
  protected readonly lists = signal<AudienceListInfo[]>([]);
  protected readonly searching = signal(false);
  protected readonly searchError = signal<string | null>(null);

  constructor(
    private readonly statusService: StatusService,
    private readonly listsService: ListsService,
  ) {
    this.loadStatus();
  }

  loadStatus(): void {
    this.statusError.set(null);
    this.statusService.getStatus().subscribe({
      next: (res) => this.status.set(res),
      error: (err) => this.statusError.set(err?.message ?? 'Failed to load status'),
    });
  }

  search(): void {
    const q = this.query().trim();
    if (!q) {
      this.lists.set([]);
      return;
    }
    this.searching.set(true);
    this.searchError.set(null);
    this.listsService.searchLists(q).subscribe({
      next: (res) => {
        this.lists.set(res.results ?? []);
        this.searching.set(false);
      },
      error: (err) => {
        this.searchError.set(err?.message ?? 'Search failed');
        this.searching.set(false);
      },
    });
  }
}
