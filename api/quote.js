// Quote form handler: validates the submission and books it onto the business
// Google Calendar as an all-day event. Auth is a Google service account; see README.
import { createSign } from 'node:crypto';

const SERVICES = ['Starlink Lease-to-Own', 'Equipment Rentals', 'Custom Installation', 'Cellular Booster', 'Other'];
const LIMITS = { name: 120, phone: 40, email: 160, location: 4000 };
const TZ = 'America/Edmonton';

export function validate(form) {
  const f = {};
  for (const k of Object.keys(LIMITS)) f[k] = String(form.get(k) ?? '').trim();
  f.service = String(form.get('service') ?? '').trim();
  for (const k of ['name', 'phone', 'email']) if (!f[k]) return { error: 'Please fill in your name, phone number and email address.' };
  for (const [k, max] of Object.entries(LIMITS)) if (f[k].length > max) return { error: 'One of the fields is too long.' };
  if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(f.email)) return { error: 'Please enter a valid email address.' };
  if (f.service && !SERVICES.includes(f.service)) return { error: 'Please choose a service from the list.' };
  return { fields: f };
}

export function buildEvent(f, today) {
  const end = new Date(`${today}T00:00:00Z`);
  end.setUTCDate(end.getUTCDate() + 1);
  const lines = [
    `Name: ${f.name}`,
    `Phone: ${f.phone}`,
    `Email: ${f.email}`,
    `Requested service: ${f.service || 'Not selected'}`,
    f.location && `\nProject location / notes:\n${f.location}`,
  ].filter(Boolean);
  return {
    summary: `Quote request: ${f.name} (${f.service || 'Other'})`,
    description: lines.join('\n'),
    start: { date: today },
    end: { date: end.toISOString().slice(0, 10) },
    transparency: 'transparent',
  };
}

async function accessToken() {
  const email = process.env.GOOGLE_SERVICE_ACCOUNT_EMAIL;
  const key = process.env.GOOGLE_PRIVATE_KEY?.replace(/\\n/g, '\n');
  if (!email || !key) throw new Error('Google credentials are not configured');
  const now = Math.floor(Date.now() / 1000);
  const b64 = (o) => Buffer.from(JSON.stringify(o)).toString('base64url');
  const unsigned = `${b64({ alg: 'RS256', typ: 'JWT' })}.${b64({
    iss: email,
    scope: 'https://www.googleapis.com/auth/calendar.events',
    aud: 'https://oauth2.googleapis.com/token',
    iat: now,
    exp: now + 3600,
  })}`;
  const sig = createSign('RSA-SHA256').update(unsigned).sign(key, 'base64url');
  const res = await fetch('https://oauth2.googleapis.com/token', {
    method: 'POST',
    body: new URLSearchParams({ grant_type: 'urn:ietf:params:oauth:grant-type:jwt-bearer', assertion: `${unsigned}.${sig}` }),
  });
  if (!res.ok) throw new Error(`token ${res.status}: ${await res.text()}`);
  return (await res.json()).access_token;
}

function reply(request, status, body) {
  if (request.headers.get('accept')?.includes('application/json')) return Response.json(body, { status });
  return new Response(null, { status: 303, headers: { Location: status < 300 ? '/?sent=1#quote' : '/?error=1#quote' } });
}

export async function POST(request) {
  let form;
  try { form = await request.formData(); } catch { return reply(request, 400, { error: 'Invalid submission.' }); }
  if (String(form.get('company') ?? '')) return reply(request, 200, { ok: true }); // honeypot: pretend success

  const { error, fields } = validate(form);
  if (error) return reply(request, 400, { error });

  try {
    const token = await accessToken();
    const today = new Intl.DateTimeFormat('en-CA', { timeZone: TZ }).format(new Date());
    const cal = encodeURIComponent(process.env.GOOGLE_CALENDAR_ID || 'primary');
    const res = await fetch(`https://www.googleapis.com/calendar/v3/calendars/${cal}/events`, {
      method: 'POST',
      headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
      body: JSON.stringify(buildEvent(fields, today)),
    });
    if (!res.ok) throw new Error(`calendar ${res.status}: ${await res.text()}`);
    return reply(request, 200, { ok: true });
  } catch (err) {
    console.error('quote submission failed', err);
    return reply(request, 502, { error: 'Sorry, something went wrong. Please call 587-416-0303.' });
  }
}
