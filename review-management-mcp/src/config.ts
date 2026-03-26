import path from 'node:path';

export interface AppConfig {
  projectRoot: string;
  accountId: string;
  clientId: string;
  clientSecret: string;
  refreshToken: string;
  locationIds: string[];
  dryRun: boolean;
  autoPostPositive: boolean;
}

function required(name: string): string {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`Missing required env: ${name}`);
  }
  return value;
}

export function loadConfig(projectRoot: string): AppConfig {
  const locationIds = Object.entries(process.env)
    .filter(([key, value]) => key.startsWith('GOOGLE_LOCATION_ID_') && Boolean(value?.trim()))
    .map(([, value]) => value!.trim());

  if (locationIds.length === 0) {
    throw new Error('Missing location ids: define at least one GOOGLE_LOCATION_ID_* env variable.');
  }

  return {
    projectRoot: path.resolve(projectRoot),
    accountId: required('GOOGLE_ACCOUNT_ID'),
    clientId: required('GOOGLE_CLIENT_ID'),
    clientSecret: required('GOOGLE_CLIENT_SECRET'),
    refreshToken: required('GOOGLE_REFRESH_TOKEN'),
    locationIds,
    dryRun: process.env.DRY_RUN === 'true',
    autoPostPositive: process.env.AUTO_POST_POSITIVE !== 'false',
  };
}
