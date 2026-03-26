export interface GoogleReview {
  id: string;
  name: string;
  locationId: string;
  reviewerName?: string;
  starRating: number;
  comment?: string;
  createTime?: string;
  reply?: { comment: string; updateTime?: string };
}

interface RequestOptions {
  method?: 'GET' | 'PUT' | 'POST' | 'DELETE';
  body?: unknown;
}

export class GoogleBusinessClient {
  constructor(private readonly baseUrl = 'https://mybusiness.googleapis.com/v4') {}

  async getReviews(locationId: string): Promise<GoogleReview[]> {
    const response = await this.request<{ reviews?: GoogleReview[] }>(
      `${this.baseUrl}/${locationId}/reviews`
    );
    return response.reviews ?? [];
  }

  async getReview(reviewName: string): Promise<GoogleReview> {
    return this.request<GoogleReview>(`${this.baseUrl}/${reviewName}`);
  }

  async postReply(reviewName: string, comment: string): Promise<void> {
    await this.request(`${this.baseUrl}/${reviewName}/reply`, {
      method: 'PUT',
      body: { comment },
    });
  }

  private async request<T = unknown>(url: string, options: RequestOptions = {}): Promise<T> {
    const retries = 3;

    for (let attempt = 1; attempt <= retries; attempt += 1) {
      const controller = new AbortController();
      const timeout = setTimeout(() => controller.abort(), 12_000);

      try {
        const response = await fetch(url, {
          method: options.method ?? 'GET',
          headers: {
            'Content-Type': 'application/json',
          },
          body: options.body ? JSON.stringify(options.body) : undefined,
          signal: controller.signal,
        });

        if (response.ok) {
          if (response.status === 204) {
            return {} as T;
          }
          return (await response.json()) as T;
        }

        if (attempt < retries && (response.status === 429 || response.status >= 500)) {
          await backoff(attempt);
          continue;
        }

        const text = await response.text();
        throw new Error(`Google API error ${response.status}: ${text}`);
      } catch (error) {
        const isLast = attempt === retries;
        if (isLast) {
          throw new Error(`Google request failed after ${retries} attempts: ${(error as Error).message}`);
        }
        await backoff(attempt);
      } finally {
        clearTimeout(timeout);
      }
    }

    throw new Error('Unreachable request state');
  }
}

function backoff(attempt: number): Promise<void> {
  const delayMs = Math.min(4000, 300 * 2 ** (attempt - 1));
  return new Promise((resolve) => setTimeout(resolve, delayMs));
}
