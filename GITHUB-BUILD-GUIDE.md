# Build the Windows Installer on GitHub (no Windows machine needed)

This repo has a GitHub Actions workflow that builds `UpFrontShopSetup.exe`
**for you, in the cloud, for free**, every time you push the code. You don't
need to own a Windows PC.

## One-time setup

### 1. Create a new GitHub repo

- Go to **https://github.com/new**
- Name it something like `upfront-shop`
- **Private** is fine (recommended)
- Do NOT tick "Add a README" — we already have one
- Click **Create repository**

GitHub will show you a page titled "…or push an existing repository from the
command line". Keep that page open.

### 2. Push this code to the repo

You need [git](https://git-scm.com/) installed on the machine you're working
from. If you don't have it, install it first.

From the folder where this README lives, open a terminal and run:

```
git init
git add .
git commit -m "Up Front Shop v1.4.0"
git branch -M main
git remote add origin https://github.com/<YOUR-USERNAME>/upfront-shop.git
git push -u origin main
```

(Replace `<YOUR-USERNAME>` with your GitHub username.)

Git will ask for credentials. Use your GitHub username and a
**personal access token** (not your password). To generate one:

- Go to **https://github.com/settings/tokens**
- Click **Generate new token (classic)**
- Tick the `repo` scope
- Copy the token (you only see it once)
- Paste it when git asks for your password

### 3. Wait for the build

- Open your repo on GitHub in the browser
- Click the **Actions** tab at the top
- You'll see a run titled **Build Windows Installer** — it starts automatically

The build takes about **4 – 6 minutes**. When it's done, the run gets a green
check mark.

### 4. Download the installer

- Click the completed run
- Scroll to the bottom — you'll see an **Artifacts** section
- Click **UpFrontShopSetup** to download a zip containing `UpFrontShopSetup.exe`
- Unzip it. That's John's installer.

## For every future release

Just push your changes:

```
git add .
git commit -m "Describe what changed"
git push
```

A fresh `UpFrontShopSetup.exe` will be built and available in the Actions tab
4–6 minutes later.

## Tagged releases (optional, cleaner)

If you want a permanent, public download page for a specific version, tag it:

```
git tag v1.4.1
git push origin v1.4.1
```

Then in addition to the build artifact, the workflow will create a
**GitHub Release** (Releases tab) with the `.exe` attached — and that gives
you a stable download URL you can share with the shop laptop.

## What the workflow does, in plain English

1. Starts a fresh Windows 11 machine in GitHub's cloud.
2. Installs Python 3.12.
3. Runs your 21 unit tests — if any fail, the build stops.
4. Runs PyInstaller to bundle the app into `UpFrontShop.exe`.
5. Installs Inno Setup 6.
6. Compiles `UpFrontShopSetup.exe` from `build\installer.iss` — the installer
   John will double-click, with the big cartoon mechanic on the welcome page.
7. Computes a SHA-256 hash of the installer.
8. Uploads both files as a downloadable artifact.
9. If you pushed a `v*` tag, also publishes them as a GitHub Release.

## Troubleshooting

**"Permission denied" when pushing.** You used your password instead of a
personal access token. Re-do step 2 with a token.

**Red X on the Actions run.** Click the run, click the failing step, read the
red error. Most common cause: a broken test — the workflow intentionally
fails early if tests don't pass, so cash-scrubbed reports or deleted-invoice
logic regressions can't accidentally ship.

**I don't see the Actions tab.** Actions is free on all GitHub accounts but
can be disabled on forks. Make sure you used **Create repository**, not Fork.

**I want the installer without pushing code.** After the very first push
kicks off a build, every future build can also be triggered manually:
Actions tab → **Build Windows Installer** → **Run workflow** button.
