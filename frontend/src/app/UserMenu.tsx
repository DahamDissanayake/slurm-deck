import { signOut } from "../api/auth";
import { InfoIcon, KeyIcon, SignOutIcon } from "../components/icons";
import { Menu } from "../components/ui/Menu";
import { navigate } from "./navigation";

/** First and last initials, e.g. "Amasha Perera" → "AP". */
export function initials(name: string) {
  const words = name.trim().split(/\s+/).filter(Boolean);
  if (!words.length) return "?";
  const first = words[0][0];
  const last = words.length > 1 ? words[words.length - 1][0] : "";
  return (first + last).toUpperCase();
}

/** The account menu behind the user's initials. */
export function UserMenu({ name }: { name: string }) {
  return (
    <Menu label={`Account: ${name}`} tooltipSide="bottom"
          icon={<span className="flex h-8 w-8 items-center justify-center rounded-full bg-accent-soft text-xs font-semibold text-accent">
            {initials(name)}
          </span>}
          items={[
            { label: "Change password", icon: <KeyIcon />, onSelect: () => navigate("/account/password") },
            { label: "About", icon: <InfoIcon />, onSelect: () => navigate("/about") },
            { label: "Sign out", icon: <SignOutIcon />, danger: true,
              onSelect: () => { signOut().finally(() => navigate("/sign-in")); } },
          ]} />
  );
}
