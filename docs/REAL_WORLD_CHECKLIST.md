# Testing a real company app: the one-page checklist

GreenLit can be pointed at any HTTP app, but a third-party site is somebody else's
property and their bot protection is doing its job. This page is the order to do
things in, and what to do when a case fails.

## Before the first request

1. **Permission first.** If the app is not on your own computer, tick "I own this
   application or have permission to test it" and record the reference (a ticket
   id, an email, a written approval). It is stored with the run, shown on the
   verdict card, and printed in every export. No reference, no run.
2. **A test or staging account, never a personal one.** Create a dedicated account
   for GreenLit. It will appear in the app's own logs, and its session may be
   revoked by the site at any time.
3. **Concurrency 1, and at least 500 ms between requests.** That is the default.
   Raising it is how a test becomes a load test, which is a different permission.
4. **Attack probes off for remote targets** unless the written permission covers
   security testing. The second checkbox exists for exactly this, and the Safety
   type is dropped from a remote run without it.
5. **Never point it at production customer data.** Use a staging dataset and a
   staging account; the answers GreenLit stores are the app's answers.

## When a case fails, read the kind first

| What you see | What it means | What to do |
| --- | --- | --- |
| `blocked_by_site` (HTTP 403) | An anti-bot or CSRF challenge page, not a wrong password | Use a normal browser session (a pasted cURL), a test account, or ask the owner to allow the runner. Do not retry harder. |
| `auth_error` (401/403) | The session expired or the token is wrong | Paste a fresh cURL or update the credentials. Cases already answered are kept. |
| `tls_error` | The certificate is self-signed, incomplete or expired | Use a trusted certificate, or test a local app over http. The message says which. |
| `dns_error` | The hostname does not resolve | Check the URL for a typo. |
| `connect_timeout` | Nothing accepted the connection in time | The host is down, or a firewall is in the way. |
| `connection_reset` | The connection closed mid-answer | The app crashed or restarted; check that it stays up for a whole answer. |
| `timeout` | The app accepted the request but did not answer in time | Raise the timeout if the app is genuinely slow, or speed the app up. |
| `redirect_blocked` | The app redirected to another host | GreenLit refuses that on purpose (SSRF safety). Point at the final URL yourself. |
| `redirect_loop` | More than three same-host redirects | Fix the redirect chain. |
| `invalid_json` | A 2xx answer that is not JSON, or is an HTML page | Check the URL points at the API, not a web page, and the response format matches. |
| `wrong_answer_path` | JSON arrived, but the answer was not where expected | The message lists the paths tried; set the answer path from the real response. |
| `response_too_large` | A body past 10 MB, or a stream past 100 KB | The URL probably answers with a file, or the app never stops talking. |
| `incomplete_stream` | A streamed answer stopped before its final event | The text is kept for diagnosis, but the case fails: a truncated answer is not a whole one. |

## When something fails and you want help

Send the **redacted** request and the structured error, nothing else:

- the cURL with every credential replaced by `XXXX` (`Authorization`, `Cookie`,
  API keys, query tokens);
- the error kind, HTTP status, and the host and path (the case detail carries
  these, without the query string);
- the run id and the case number.

Never send a real password, session cookie or customer answer.

## What this does not promise

Unknown behaviour of a third-party app can still surface new cases; GreenLit
reports them as structured errors rather than crashing, hanging, scoring them
wrong, or leaking a secret — that is a reduction in known failure classes, not a
guarantee that nothing new can happen.
