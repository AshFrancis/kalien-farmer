/**
 * Cloudflare Worker for Kalien Web Farmer.
 *
 * 1. Serves static assets (HTML, JS, WASM) from the site bucket.
 * 2. Proxies /api/* requests to kalien.xyz with CORS headers.
 * 3. Adds Cross-Origin-Opener-Policy / Cross-Origin-Embedder-Policy
 *    headers required for SharedArrayBuffer (WASM threads).
 */

const API_ORIGIN = "https://kalien.xyz";

// COOP/COEP headers required for SharedArrayBuffer
const ISOLATION_HEADERS = {
	"Cross-Origin-Opener-Policy": "same-origin",
	"Cross-Origin-Embedder-Policy": "require-corp",
};

// CORS headers for API proxy responses
const CORS_HEADERS = {
	"Access-Control-Allow-Origin": "*",
	"Access-Control-Allow-Methods": "GET, POST, OPTIONS",
	"Access-Control-Allow-Headers": "Content-Type",
};

export default {
	async fetch(request, env) {
		const url = new URL(request.url);

		// ── CORS preflight ──
		if (request.method === "OPTIONS" && url.pathname.startsWith("/api/")) {
			return new Response(null, {
				status: 204,
				headers: CORS_HEADERS,
			});
		}

		// ── API proxy ──
		if (url.pathname.startsWith("/api/")) {
			return proxyAPI(request, url);
		}

		// ── Static assets ──
		return serveStatic(request, url, env);
	},
};

async function proxyAPI(request, url) {
	// Forward to kalien.xyz
	const targetUrl = API_ORIGIN + url.pathname + url.search;

	const init = {
		method: request.method,
		headers: {
			"User-Agent": "kalien-web-farmer/1.0",
		},
	};

	// Forward body for POST
	if (request.method === "POST") {
		init.body = await request.arrayBuffer();
		const ct = request.headers.get("Content-Type");
		if (ct) init.headers["Content-Type"] = ct;
	}

	try {
		const resp = await fetch(targetUrl, init);
		const body = await resp.arrayBuffer();

		// Return with CORS headers
		return new Response(body, {
			status: resp.status,
			headers: {
				"Content-Type": resp.headers.get("Content-Type") || "application/json",
				...CORS_HEADERS,
			},
		});
	} catch (e) {
		return new Response(JSON.stringify({ error: e.message }), {
			status: 502,
			headers: {
				"Content-Type": "application/json",
				...CORS_HEADERS,
			},
		});
	}
}

async function serveStatic(request, url, env) {
	// Resolve path
	let path = url.pathname;
	if (path === "/" || path === "") path = "/index.html";

	// Try to get asset from KV (Workers Sites) or fall back to __STATIC_CONTENT
	try {
		// For Cloudflare Pages / Workers Sites with asset binding
		const asset = await env.__STATIC_CONTENT?.get(path.slice(1));
		if (!asset) {
			return new Response("Not found", { status: 404 });
		}

		const contentType = getContentType(path);
		const headers = new Headers({
			"Content-Type": contentType,
			...ISOLATION_HEADERS,
		});

		// WASM and JS files also need cross-origin isolation
		if (path.endsWith(".js") || path.endsWith(".wasm")) {
			headers.set("Cross-Origin-Resource-Policy", "same-origin");
		}

		// Cache static assets
		if (path.endsWith(".wasm") || path.endsWith(".js")) {
			headers.set("Cache-Control", "public, max-age=86400");
		}

		return new Response(asset, { headers });
	} catch (e) {
		return new Response("Internal error: " + e.message, { status: 500 });
	}
}

function getContentType(path) {
	const ext = path.split(".").pop()?.toLowerCase();
	const types = {
		html: "text/html; charset=utf-8",
		js: "application/javascript",
		wasm: "application/wasm",
		json: "application/json",
		css: "text/css",
		png: "image/png",
		ico: "image/x-icon",
	};
	return types[ext] || "application/octet-stream";
}
