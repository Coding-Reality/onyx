import { User } from "@/lib/types";
import { fetchSS } from "@/lib/utilsSS";

export async function getCurrentUserSS(): Promise<User | null> {
  try {
    const response = await fetchSS("/me", {
      credentials: "include",
      next: { revalidate: 0 },
    });

    if (!response.ok) return null;

    const user = await response.json();
    return user;
  } catch (e) {
    console.log(`Error fetching user: ${e}`);
    return null;
  }
}
