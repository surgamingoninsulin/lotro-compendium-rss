# LOTRO Plugin Feed

Turns the LoTROInterface Plugin Compendium API
(`https://api.lotrointerface.com/fav/plugincompendium.xml`) into normal RSS feeds
you can use in Feeder or any other RSS reader. Free: runs on GitHub Actions and
GitHub Pages.

## Feeds you get

| Feed | Link (replace USER and REPO) |
|---|---|
| All plugins, newest update first | `https://USER.github.io/REPO/feed.xml` |
| Latest 100 updates | `https://USER.github.io/REPO/latest.xml` |
| One category, e.g. Raiding & Instances | `https://USER.github.io/REPO/categories/raiding-instances.xml` |
| Overview page with every link | `https://USER.github.io/REPO/` |

Every new plugin version appears in Feeder as a new unread item.

## Setup (one time, about 5 minutes)

1. **Create a repository** on GitHub, e.g. `lotro-plugin-feed`. Make it **public**
   (GitHub Pages is free for public repos).
2. **Upload the files** with *Add file → Upload files*, keeping the folders:
   ```
   build_feed.py
   README.md
   .github/workflows/build-feed.yml
   ```
   Tip: the `.github` folder is hidden on some systems. If you can't drag it in,
   use *Add file → Create new file* and type `.github/workflows/build-feed.yml`
   as the name, then paste the contents.
3. **Allow the workflow to push:** *Settings → Actions → General → Workflow
   permissions* → select **Read and write permissions** → Save.
4. **Run it once:** *Actions* tab → **Build LOTRO plugin feed** → **Run workflow**.
   After about a minute a `docs/` folder appears in the repo.
5. **Turn on Pages:** *Settings → Pages → Source: Deploy from a branch* →
   Branch **main**, folder **/docs** → Save. Wait 1–2 minutes.
6. **Open** `https://USER.github.io/REPO/` and copy the feed link you want into Feeder.

After that it updates itself every 3 hours.

## Notes

- If the API is down or returns fewer than 50 plugins, the run fails on purpose and
  the last good feed stays online.
- GitHub pauses scheduled workflows after 60 days without commits. Plugin updates
  create commits, so that normally won't happen; if it does, click **Enable
  workflow** in the Actions tab.
- Test locally (Python 3.9+, no installs): `python build_feed.py --out docs`
