import dotenv from 'dotenv';

dotenv.config();

const locationId = process.env.GOOGLE_LOCATION_ID_MAIN || process.env.GOOGLE_LOCATION_ID_1;
if (!locationId) {
  throw new Error('Missing GOOGLE_LOCATION_ID_MAIN or GOOGLE_LOCATION_ID_1 in .env');
}

console.log(`Connection test configured for location: ${locationId}`);
