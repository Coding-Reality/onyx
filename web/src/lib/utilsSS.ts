import { cookies, headers } from "next/headers";
import {
  HOST_URL,
  INTERNAL_URL,
  SERVER_SIDE_ONLY__AUTH_COOKIE_NAME,
} from "./constants";
import { ReadonlyRequestCookies } from "next/dist/server/web/spec-extension/adapters/request-cookies";

export function processCookies(cookies: ReadonlyRequestCookies): string {
  let cookieString = cookies
    .getAll()
    .map((cookie) => `${cookie.name}=${cookie.value}`)
    .join("; ");

  // Inject debug auth cookie for local development against remote backend
  // only when the normal auth cookie is not already present.
  if (process.env.DEBUG_AUTH_COOKIE && process.env.NODE_ENV === "development") {
    const hasAuthCookie = cookieString
      .split(/;\s*/)
      .some((cookie) =>
        cookie.startsWith(`${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=`)
      );
    if (!hasAuthCookie) {
      const debugCookie = `${SERVER_SIDE_ONLY__AUTH_COOKIE_NAME}=${process.env.DEBUG_AUTH_COOKIE}`;
      cookieString = cookieString
        ? `${cookieString}; ${debugCookie}`
        : debugCookie;
    }
  }

  return cookieString;
}

export function buildClientUrl(path: string) {
  if (path.startsWith("/")) {
    return `${HOST_URL}${path}`;
  }
  return `${HOST_URL}/${path}`;
}

export function buildUrl(path: string) {
  if (path.startsWith("/")) {
    return `${INTERNAL_URL}${path}`;
  }
  return `${INTERNAL_URL}/${path}`;
}

export class UrlBuilder {
  private url: URL;

  constructor(baseUrl: string) {
    try {
      this.url = new URL(baseUrl);
    } catch {
      // Handle relative URLs by prepending a base
      this.url = new URL(baseUrl, "http://placeholder.com");
    }
  }

  addParam(key: string, value: string | number | boolean): UrlBuilder {
    this.url.searchParams.set(key, String(value));
    return this;
  }

  addParams(params: Record<string, string | number | boolean>): UrlBuilder {
    Object.entries(params).forEach(([key, value]) => {
      this.url.searchParams.set(key, String(value));
    });
    return this;
  }

  toString(): string {
    // Extract just the path and query parts for relative URLs
    if (this.url.origin === "http://placeholder.com") {
      return `${this.url.pathname}${this.url.search}`;
    }
    return this.url.toString();
  }

  static fromInternalUrl(path: string): UrlBuilder {
    return new UrlBuilder(buildUrl(path));
  }

  static fromClientUrl(path: string): UrlBuilder {
    return new UrlBuilder(buildClientUrl(path));
  }
}

export async function fetchSS(url: string, options?: RequestInit) {
  const cookieString = processCookies(await cookies());
  const incomingHeaders = await headers();
  const requestHost = (
    incomingHeaders.get("x-forwarded-host") ?? incomingHeaders.get("host")
  )
    ?.split(",", 1)[0]
    ?.trim();
  const configuredHost = new URL(HOST_URL).host;
  const tenantHost = configuredHost || requestHost;
  const requestHeaders = new Headers(options?.headers);
  requestHeaders.set("cookie", cookieString);

  // INTERNAL_URL points at the Kubernetes service, but tenancy is resolved
  // from an operator-owned external host map. WEB_DOMAIN is the authoritative
  // external host for this server instance; Next.js may normalize request
  // context headers to its internal service name during server rendering.
  // The backend still fails closed if this configured host is not mapped.
  if (tenantHost) {
    requestHeaders.set("host", tenantHost);
    requestHeaders.set("x-forwarded-host", tenantHost);
  }

  const init: RequestInit = {
    credentials: "include",
    cache: "no-store",
    ...options,
    headers: requestHeaders,
  };

  return fetch(buildUrl(url), init);
}
