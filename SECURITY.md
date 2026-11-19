# Security policy

AI Data Analyst runs SQL and Python code that an AI writes, so security is part of
the design, not an extra. This page explains how to report a problem, what happens
after you report it, and how the app protects you.

## Supported versions

Security fixes go into the `main` branch and ship in the next release.

| Version | Supported |
| --- | --- |
| Latest release | Yes |
| `main` branch | Yes |
| Older releases | No |

If you use an older release, please upgrade to the latest one.

## Reporting a vulnerability

**Please do not open a public issue, pull request or discussion for a security
problem.** A public report shows everyone how to attack the app before a fix
exists.

Report it privately with GitHub's private vulnerability reporting instead:

1. Open the repository's **Security** tab.
2. Click **Report a vulnerability**.
3. Fill in the form and submit it.

You can also open the form directly:
<https://github.com/MITRAKER/ai-data-analyst/security/advisories/new>

The report stays private between you and the maintainer while the problem is
fixed.

Examples of what to report:

- SQL other than a single read-only `SELECT` that gets past the SQL guard.
- SQL that reads or writes files, or changes DuckDB's settings.
- AI-written Python that gets around the sandbox checks or its limits.
- A way to read the API key or other secrets.
- A weakness in the CI or release workflows, for example a way to run code with
  the workflows' permissions.

The known limits described under [Security model](#security-model) are not new
vulnerabilities. A way around one of the protection layers is.

## What to include in a report

- What the problem is, and what an attacker could do with it.
- The version or commit you tested.
- Steps to reproduce it, ideally with the smallest input that shows the problem:
  a CSV file, a SQL query, a question for the agent or a piece of Python code.
- Any logs or error output.
- Your idea for a fix, if you have one.
- Whether you want to be credited, and under which name.

Please remove API keys and personal data from everything you send. Made-up data
or `data/sample_sales.csv` works well for examples.

## What to expect

This is a personal project, so responses are best effort. The aim is to:

- acknowledge your report within 7 days;
- tell you whether the problem is confirmed, and what the plan is;
- keep you informed while the fix is in progress;
- credit you in the published advisory, unless you prefer not to be named.

The fix ships in a new release. A GitHub security advisory describes the problem,
and `CHANGELOG.md` lists the fix under "Security". Please keep the details private
until then.

## Security model

The AI writes SQL and Python, and the app runs them. The AI can make mistakes.
Text inside an uploaded file can also try to trick it into doing something
harmful; this is called prompt injection. So the app treats every query and every
piece of code from the AI as untrusted, and checks it with several independent
layers. This is called defense in depth: if one layer fails, the next one still
protects you.

### SQL

1. **Parsed, not pattern-matched.** DuckDB's own parser splits the SQL into
   statements and reports the type of each one. Only a single `SELECT` statement
   is allowed. A text check could be fooled by `SELECT 1; DROP TABLE sales`. The
   parser sees two statements, so the query is refused.
2. **No access to files.** DuckDB runs with external file access disabled, so SQL
   cannot read or write files on the server, for example with
   `read_csv('/etc/passwd')` or `COPY ... TO`. DuckDB's configuration is locked,
   so SQL cannot turn that setting back on.
3. **Capped results.** Every result is capped at a maximum number of rows. A flag
   in the result says when rows were cut off, so one query cannot return millions
   of rows. DuckDB also runs with a memory limit, and a query that runs too long
   is stopped.

### Python

4. **Checked before it runs.** The app parses the code into a syntax tree (AST)
   and inspects it before anything runs. Imports must be on an allow-list, such as
   `pandas`, `numpy` and `math`, and a name imported from one of them must not be
   private (`from random import _os` is refused). Dangerous built-ins, such as
   `open`, `eval`, `exec` and `__import__`, are banned. So are file and network
   methods, such as `read_csv` and `to_csv`, and the doors to Python's internals,
   such as frames and the `builtins` module.
5. **Run in a separate, locked-down process.** The code runs in a new process of
   the same Python interpreter, never inside the server itself. It starts in an
   empty working directory, and its environment holds no secrets. Just before the
   code starts, that process limits itself: CPU time, memory, no writing to files,
   no new file descriptors at all (so it cannot open a file or a network
   connection, even after closing one it already has), and no new processes or
   threads. A wall-clock time limit stops it from the outside.
6. **Watched while it runs.** An audit hook
   ([PEP 578](https://peps.python.org/pep-0578/)) in that process refuses opening
   files, starting programs, sending signals, sockets, `ctypes`, changing the
   limits, and importing modules that could get around them. Only the code's
   printed output and error messages come back.

A check of the syntax tree can never be complete, because Python is a very
flexible language. So layers 5 and 6 do not rely on it: the tests run code that
the check would refuse, for example code that closes a file descriptor to open a
file, or that tries to send a signal to the server, and check that it still
fails.

### What these layers do not do

These layers reduce the risk. They are not a perfect sandbox. All the limits are
set by the app itself, inside your normal operating system: there is no
container or virtual machine around the code. Code that found a way past all of
them, for example through a bug in Python itself, would run as the same
operating-system user as the server, on the same machine. The root user is
exempt from the limit on new processes, so do not run the app as root. The
Docker image runs it as an ordinary user.

That is a reasonable trade-off when you run the app on your own computer, with
your own data and your own API key. A multi-user deployment should add
container-level isolation around the code runner, for example gVisor or
Firecracker (a lightweight virtual machine), with no network access.

Also keep in mind:

- **No login.** The API has no authentication and no rate limits. Anyone who can
  reach it can upload data, read every dataset and ask the agent questions, which
  spends your API credits. Run it on your own computer, or put authentication in
  front of it before other people can reach it.
- **Size limits.** Uploads, SQL text, query results and the number of datasets
  all have size limits, so one request cannot make the app grow without bound.
- **A limited agent loop.** The agent stops after a fixed number of steps, so a
  confused agent cannot loop, and spend money, forever.
- **A non-root container.** The Docker image runs the app as an ordinary user,
  not as root. The installed code belongs to root, so the app cannot change its
  own code. CI starts the image on every pull request and checks both.

## Secrets

- The app reads `ANTHROPIC_API_KEY` from the environment, or from a `.env` file.
  To create one, copy `.env.example` to `.env` and add your key. `.env` is listed
  in `.gitignore`, so git ignores it.
- Never commit keys, tokens or passwords: not in code, tests, notebooks,
  screenshots or issue reports. The tests use a fake Claude client and never need
  a key.
- The detect-secrets and detect-private-key hooks look for keys, tokens,
  passwords and private keys before each commit, and CI runs them on every file
  of every pull request. GitHub's secret scanning also checks the repository and
  its whole history; it knows the format of Anthropic API keys. Turn on **push
  protection** (repository **Settings** > **Advanced Security**) so GitHub
  blocks a push that contains one. These checks are a safety net, not a
  guarantee.
- The Docker image never contains your key. Pass it in when you start a container
  with `-e ANTHROPIC_API_KEY`. With no value after the name, Docker copies the key
  from your shell, so it does not appear in the command either.

### If a key leaks

1. **Revoke it immediately** in the Anthropic Console (now called the Claude
   Console), on the API keys page: <https://platform.claude.com/settings/keys>.
   Assume someone copied the key as soon as it was exposed, because automated
   tools scan public repositories for keys all the time. Then create a new key and
   put it in your `.env` file.
2. **Then remove it from the git history.** Deleting the key in a new commit is
   not enough, because older commits still contain it. Follow GitHub's guide
   [Removing sensitive data from a repository](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/removing-sensitive-data-from-a-repository).
   Revoking the key is what protects you. Cleaning the history stops the old key
   from staying in the repository.
3. **Check your usage** in the Console for requests you did not make.

If you find someone else's key in this repository, do not use it. Report it
privately, as described in [Reporting a vulnerability](#reporting-a-vulnerability).

## Automated security checks

- **Ruff's `S` rules**, the Bandit security checks, run in pre-commit and in CI.
- **CodeQL** analyzes the Python code and the GitHub Actions workflows on every
  pull request and once a week. Findings appear in the **Security** tab.
- **pip-audit** checks the dependencies for known vulnerabilities in CI. Run it
  yourself with `make security`.
- **Dependabot** opens weekly pull requests to update the Python packages, the
  GitHub Actions and the Docker base image. It waits until a new version is 7
  days old, because a hacked release is usually found and removed within days.
  Security updates do not wait.
- **zizmor** checks the GitHub Actions workflows for security mistakes, such as
  script injection or tokens with too many permissions, before each commit and
  in CI.
- **Least privilege in CI.** Every workflow gives its token only the permissions
  it needs, mostly read-only. The workflows use only GitHub's own actions;
  everything else is plain shell commands. To build the image for ARM computers,
  the release job also runs Docker's own build tools from container images:
  BuildKit, and the QEMU installer `tonistiigi/binfmt`, which needs full rights
  on the runner and is therefore pinned to one exact build by its digest.
- **detect-secrets** and **detect-private-key** scan for secrets, as described
  above.
- **Release images** come with a provenance record (how and from what the image
  was built) and an SBOM (the list of every package in it).
