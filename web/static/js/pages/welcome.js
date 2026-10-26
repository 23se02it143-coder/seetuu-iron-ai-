// The whole site can require sign-in (REQUIRE_LOGIN=true): "/" then redirects here with the page the
// visitor originally wanted in ?next=. The auth dialog itself is already on every page via base.html;
// this just sends them on once shell.js reports a signed-in user.
import { onUser } from "../shell.js";

const next = new URLSearchParams(location.search).get("next");
const target = next && next.startsWith("/") && !next.startsWith("//") ? next : "/";

onUser((user) => {
  if (user) location.href = target;
});
