// Cloudflare Worker to serve HLS assets from R2 with correct headers
// Bind your R2 bucket in wrangler.toml as `VIDEO_BUCKET`

const CONTENT_TYPES = new Map([
  ['.m3u8', 'application/vnd.apple.mpegurl'],
  ['.ts', 'video/MP2T'],
]);

function guessContentType(key) {
  const lower = key.toLowerCase();
  for (const [ext, type] of CONTENT_TYPES.entries()) {
    if (lower.endsWith(ext)) return type;
  }
  // Minimal set for static files
  if (lower.endsWith('.mp4')) return 'video/mp4';
  if (lower.endsWith('.mpd')) return 'application/dash+xml';
  return 'application/octet-stream';
}

function cacheHeaders(key) {
  // Cache segments longer than playlists
  if (key.endsWith('.ts')) {
    return 'public, max-age=86400, immutable'; // 1 day
  }
  if (key.endsWith('.m3u8')) {
    return 'public, max-age=30'; // refresh playlist frequently
  }
  return 'public, max-age=3600';
}

function corsHeaders(methods = 'GET,HEAD,OPTIONS') {
  return {
    'Access-Control-Allow-Origin': '*',
    'Access-Control-Allow-Methods': methods,
    'Access-Control-Allow-Headers': 'Content-Type, Range, Origin, Accept',
  };
}

export default {
  async fetch(request, env) {
    const url = new URL(request.url);

    // CORS preflight
    if (request.method === 'OPTIONS') {
      return new Response(null, { status: 204, headers: corsHeaders() });
    }

    const root = env.KEY_ROOT || 'videos';
    // Expecting paths like /<root>/<video_id>/playlist.m3u8 or segments
    if (!url.pathname.startsWith(`/${root}/`)) {
      // Simple health/info endpoint
      if (url.pathname === '/' || url.pathname === '/health') {
        return new Response('OK', { status: 200 });
      }
      return new Response('Not Found', { status: 404 });
    }

    const key = url.pathname.replace(/^\//, ''); // remove leading slash

    // Fetch object from R2
    const object = await env.VIDEO_BUCKET.get(key);
    if (!object) {
      return new Response('Not Found', { status: 404, headers: corsHeaders() });
    }

    const type = guessContentType(key);
    const headers = new Headers();
    headers.set('Content-Type', type);
    headers.set('Cache-Control', cacheHeaders(key));
    headers.set('Accept-Ranges', 'bytes');
    for (const [k, v] of Object.entries(corsHeaders())) headers.set(k, v);

    if (request.method === 'HEAD') {
      return new Response(null, { status: 200, headers });
    }

    return new Response(object.body, { status: 200, headers });
  },
};
