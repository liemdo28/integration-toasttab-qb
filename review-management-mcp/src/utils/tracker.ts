import fs from 'node:fs';
import path from 'node:path';

export type Platform = 'google';

export interface ReviewState {
  review_key: string;
  platform: Platform;
  location: string;
  review_id: string;
  first_seen_at: string;
  last_seen_at: string;
  google_has_reply: boolean;
  posted_by_system: boolean;
  posted_response_text?: string;
  posted_at?: string;
  needs_owner_approval: boolean;
  resolved_at?: string;
}

interface TrackerStore {
  responded: Record<string, ReviewState>;
}

export class ResponseTracker {
  private readonly historyPath: string;
  private readonly store: TrackerStore;

  constructor(projectRoot: string) {
    this.historyPath = path.join(projectRoot, 'logs', 'response-history.json');
    fs.mkdirSync(path.dirname(this.historyPath), { recursive: true });
    this.store = this.load();
  }

  static key(platform: Platform, location: string, reviewId: string): string {
    return `${platform}:${location}:${reviewId}`;
  }

  hasResponded(platform: Platform, location: string, reviewId: string): boolean {
    return Boolean(this.store.responded[ResponseTracker.key(platform, location, reviewId)]);
  }

  markObserved(params: {
    platform: Platform;
    location: string;
    reviewId: string;
    googleHasReply: boolean;
    needsOwnerApproval: boolean;
  }): void {
    const key = ResponseTracker.key(params.platform, params.location, params.reviewId);
    const now = new Date().toISOString();
    const current = this.store.responded[key];
    this.store.responded[key] = {
      review_key: key,
      platform: params.platform,
      location: params.location,
      review_id: params.reviewId,
      first_seen_at: current?.first_seen_at ?? now,
      last_seen_at: now,
      google_has_reply: params.googleHasReply,
      posted_by_system: current?.posted_by_system ?? false,
      posted_response_text: current?.posted_response_text,
      posted_at: current?.posted_at,
      needs_owner_approval: params.needsOwnerApproval,
      resolved_at: params.googleHasReply ? now : current?.resolved_at,
    };
    this.save();
  }

  markResponded(params: {
    platform: Platform;
    location: string;
    reviewId: string;
    responseText: string;
    needsOwnerApproval: boolean;
  }): void {
    const key = ResponseTracker.key(params.platform, params.location, params.reviewId);
    const now = new Date().toISOString();
    const current = this.store.responded[key];
    this.store.responded[key] = {
      review_key: key,
      platform: params.platform,
      location: params.location,
      review_id: params.reviewId,
      first_seen_at: current?.first_seen_at ?? now,
      last_seen_at: now,
      google_has_reply: true,
      posted_by_system: true,
      posted_response_text: params.responseText,
      posted_at: now,
      needs_owner_approval: params.needsOwnerApproval,
      resolved_at: now,
    };
    this.save();
  }

  private load(): TrackerStore {
    if (!fs.existsSync(this.historyPath)) {
      return { responded: {} };
    }

    const raw = fs.readFileSync(this.historyPath, 'utf8');
    const parsed = JSON.parse(raw) as Partial<TrackerStore>;
    return {
      responded: parsed.responded ?? {},
    };
  }

  private save(): void {
    fs.writeFileSync(this.historyPath, JSON.stringify(this.store, null, 2), 'utf8');
  }
}
