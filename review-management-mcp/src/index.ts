import fs from 'node:fs';
import path from 'node:path';

import { GoogleBusinessClient, GoogleReview } from './clients/google';
import { loadConfig } from './config';
import { ResponseTracker } from './utils/tracker';

const PROJECT_ROOT = path.resolve(__dirname, '..');
const PENDING_MD = path.join(PROJECT_ROOT, 'logs', 'pending-reviews.md');

export class ReviewServer {
  private readonly config = loadConfig(PROJECT_ROOT);
  private readonly client = new GoogleBusinessClient();
  private readonly tracker = new ResponseTracker(PROJECT_ROOT);

  async listNewReviews(sinceDate?: string): Promise<GoogleReview[]> {
    const all = await this.fetchAllReviews();

    return all.filter((r) => {
      const notRepliedOnGoogle = !r.reply;
      const unseenBySystem = !this.tracker.hasResponded('google', r.locationId, r.id);
      const afterSince = sinceDate ? new Date(r.createTime ?? 0) >= new Date(sinceDate) : true;
      return notRepliedOnGoogle && unseenBySystem && afterSince;
    });
  }

  async listAllReviews(unansweredOnly = false): Promise<GoogleReview[]> {
    const all = await this.fetchAllReviews();

    if (!unansweredOnly) {
      return all;
    }

    return all.filter((r) => !r.reply && !this.tracker.hasResponded('google', r.locationId, r.id));
  }

  async postReviewResponse(params: {
    reviewName: string;
    reviewId: string;
    locationId: string;
    responseText: string;
    approvedByOwner?: boolean;
    starRating: number;
  }): Promise<{ status: 'queued' | 'posted' | 'dry_run' }> {
    const needsOwnerApproval = params.starRating <= 2;
    const approved = Boolean(params.approvedByOwner);

    if (needsOwnerApproval && !approved) {
      this.savePendingReview(params);
      this.tracker.markObserved({
        platform: 'google',
        location: params.locationId,
        reviewId: params.reviewId,
        googleHasReply: false,
        needsOwnerApproval,
      });
      return { status: 'queued' };
    }

    if (this.config.dryRun) {
      this.tracker.markObserved({
        platform: 'google',
        location: params.locationId,
        reviewId: params.reviewId,
        googleHasReply: false,
        needsOwnerApproval,
      });
      return { status: 'dry_run' };
    }

    await this.client.postReply(params.reviewName, params.responseText);
    this.tracker.markResponded({
      platform: 'google',
      location: params.locationId,
      reviewId: params.reviewId,
      responseText: params.responseText,
      needsOwnerApproval,
    });

    return { status: 'posted' };
  }

  private savePendingReview(input: {
    reviewId: string;
    locationId: string;
    responseText: string;
    starRating: number;
  }): void {
    fs.mkdirSync(path.dirname(PENDING_MD), { recursive: true });
    const line = `- ${new Date().toISOString()} | ${input.locationId}:${input.reviewId} | ${input.starRating}★ | ${input.responseText}\n`;
    fs.appendFileSync(PENDING_MD, line, 'utf8');
  }

  private async fetchAllReviews(): Promise<GoogleReview[]> {
    const entries = await Promise.all(this.config.locationIds.map(async (locationId) => {
      const reviews = await this.client.getReviews(locationId);
      return reviews.map((r) => {
        this.tracker.markObserved({
          platform: 'google',
          location: locationId,
          reviewId: r.id,
          googleHasReply: Boolean(r.reply),
          needsOwnerApproval: r.starRating <= 2,
        });
        return { ...r, locationId };
      });
    }));

    return entries.flat();
  }
}

