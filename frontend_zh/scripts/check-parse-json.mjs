function formatApiErrorDetail(detail) {
  if (typeof detail === 'string') {
    return detail.trim();
  }

  if (Array.isArray(detail)) {
    const parts = detail.map((item) => formatApiErrorDetail(item)).filter(Boolean);
    return parts.join('; ');
  }

  if (detail && typeof detail === 'object') {
    const message = typeof detail.msg === 'string' ? detail.msg.trim() : '';
    const location = Array.isArray(detail.loc)
      ? detail.loc.map((part) => String(part)).join('.')
      : '';
    const nestedDetail = formatApiErrorDetail(detail.detail);

    if (message && location) return `${location}: ${message}`;
    if (message) return message;
    if (nestedDetail) return nestedDetail;
  }

  return '';
}

async function parseJson(response) {
  const raw = await response.text();
  let data = null;

  if (raw) {
    try {
      data = JSON.parse(raw);
    } catch {
      if (!response.ok) {
        throw new Error(raw.trim() || `Request failed: ${response.status}`);
      }
      throw new Error(`Invalid JSON response: ${raw.slice(0, 160)}`);
    }
  }

  if (!response.ok || data?.success === false) {
    const detail = formatApiErrorDetail(data?.detail);
    const message = typeof data?.message === 'string' ? data.message.trim() : '';
    const nestedErrorMessage =
      typeof data?.error?.message === 'string' ? data.error.message.trim() : '';
    const fallback = raw.trim() || response.statusText || `Request failed: ${response.status}`;
    throw new Error(detail || message || nestedErrorMessage || fallback);
  }

  return data;
}

function makeResponse({ body, ok = true, status = 200, statusText = 'OK' }) {
  return {
    ok,
    status,
    statusText,
    async text() {
      return body;
    },
  };
}

const checks = [
  {
    name: 'empty body returns null instead of JSON parse exception',
    run: async () => {
      const data = await parseJson(makeResponse({ body: '' }));
      if (data !== null) throw new Error(`expected null, got ${JSON.stringify(data)}`);
    },
  },
  {
    name: 'invalid ok body is surfaced as Invalid JSON response',
    run: async () => {
      try {
        await parseJson(makeResponse({ body: '<html>oops</html>' }));
      } catch (error) {
        if (!String(error?.message || '').includes('Invalid JSON response')) {
          throw error;
        }
        return;
      }
      throw new Error('expected parser to throw');
    },
  },
  {
    name: 'valid json body parses successfully',
    run: async () => {
      const data = await parseJson(makeResponse({ body: '{"success":true,"notebooks":[]}' }));
      if (!Array.isArray(data?.notebooks)) {
        throw new Error(`unexpected payload ${JSON.stringify(data)}`);
      }
    },
  },
];

for (const check of checks) {
  await check.run();
  console.log(`ok - ${check.name}`);
}
