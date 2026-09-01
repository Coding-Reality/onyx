import { cookies, headers } from "next/headers";
import { HOST_URL, INTERNAL_URL } from "./constants";
import { processCookies } from "@/lib/users/svcSS";

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
  const originalHost = (
    incomingHeaders.get("x-forwarded-host") ?? incomingHeaders.get("host")
  )
    ?.split(",", 1)[0]
    ?.trim();
  const requestHeaders = new Headers(options?.headers);
  requestHeaders.set("cookie", cookieString);

  // INTERNAL_URL points at the Kubernetes service, but tenancy is resolved
  // from an operator-owned external host map. Preserve the original request
  // host for server-side API calls; the backend still fails closed when that
  // host is not mapped and never trusts a caller-supplied tenant ID.
  if (originalHost) {
    requestHeaders.set("host", originalHost);
    requestHeaders.set("x-forwarded-host", originalHost);
  }

  const init: RequestInit = {
    credentials: "include",
    cache: "no-store",
    ...options,
    headers: requestHeaders,
  };

  return fetch(buildUrl(url), init);
}
