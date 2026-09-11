import { NextRequest } from "next/server";
import { POST } from "@/app/auth/logout/route";
import { getFederatedLogoutUrlSS, logoutSS } from "@/lib/auth/svcSS";

jest.mock("server-only", () => ({}), { virtual: true });

jest.mock("@/lib/auth/svcSS", () => ({
  getFederatedLogoutUrlSS: jest.fn(),
  logoutSS: jest.fn(),
}));

jest.mock("@/lib/constants", () => ({
  SERVER_SIDE_ONLY__AUTH_COOKIE_NAME: "fastapiusersauth",
}));

const mockedGetFederatedLogoutUrlSS = jest.mocked(getFederatedLogoutUrlSS);
const mockedLogoutSS = jest.mocked(logoutSS);

beforeEach(() => {
  jest.clearAllMocks();
  mockedLogoutSS.mockResolvedValue(new Response(null, { status: 204 }));
  mockedGetFederatedLogoutUrlSS.mockResolvedValue(null);
});

it("returns the IdP logout URL for an explicit federated logout", async () => {
  const logoutUrl =
    "https://idp.example.com/logout?client_id=onyx&post_logout_redirect_uri=https%3A%2F%2Fonyx.example.com%2Fauth%2Flogin";
  mockedGetFederatedLogoutUrlSS.mockResolvedValue(logoutUrl);
  const request = new NextRequest(
    "https://onyx.example.com/auth/logout?federated=true",
    { method: "POST" }
  );

  const response = await POST(request);

  expect(mockedGetFederatedLogoutUrlSS).toHaveBeenCalledWith(request.headers);
  expect(mockedLogoutSS).toHaveBeenCalledWith(request.headers);
  expect(response.headers.get("X-Onyx-Federated-Logout-Url")).toBe(logoutUrl);
  expect(response.headers.getSetCookie()[0]).toContain(
    "fastapiusersauth=; Max-Age=0"
  );
});

it("keeps automatic and expiry-driven logout local", async () => {
  const request = new NextRequest("https://onyx.example.com/auth/logout", {
    method: "POST",
  });

  const response = await POST(request);

  expect(mockedGetFederatedLogoutUrlSS).not.toHaveBeenCalled();
  expect(mockedLogoutSS).toHaveBeenCalledWith(request.headers);
  expect(response.headers.has("X-Onyx-Federated-Logout-Url")).toBe(false);
});
