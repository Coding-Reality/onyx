import { selectTenantHost } from "./tenantHost";

describe("selectTenantHost", () => {
  it("preserves the tenant hostname from the incoming request", () => {
    expect(
      selectTenantHost(
        "tlm.onyx.cloud.coding-reality.com",
        "onyx.cloud.coding-reality.com"
      )
    ).toBe("tlm.onyx.cloud.coding-reality.com");
  });

  it("falls back to the configured hostname without request context", () => {
    expect(selectTenantHost(undefined, "onyx.cloud.coding-reality.com")).toBe(
      "onyx.cloud.coding-reality.com"
    );
  });
});
