export function selectTenantHost(
  requestHost: string | undefined,
  configuredHost: string
): string {
  return requestHost || configuredHost;
}
