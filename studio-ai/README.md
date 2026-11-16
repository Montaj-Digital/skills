# Studio AI

**Version 0.8.0** (short-form 2.7.0, long-form 0.8.0): your brand's own social planner. **Post it** writes each
platform's post with Claude; the **Calendar** schedules and posts them (YouTube, Facebook, Instagram, TikTok and
LinkedIn once the developer links them; the rest by hand with an email reminder); **Results** shows how they do.
**0.7.0:** the AI studio and inserts. **0.5.0:** client brand kits.

Short-form and long-form editing in **your brand's look or any
client's own brand**, plus the **AI studio**: Claude builds a clip (a trailer, a cold open, a testimonial cut) from
several videos, and you lay it over the video or insert it, and the **social planner** for your brand's own
channels. It runs on your own Mac.

Open it with `Open Studio AI.command`; it runs at http://127.0.0.1:4322.

Installing: `04. Installation/INSTALL.md`. 

## Client brands

1. **Brands** (in the header) → **Add a client**.
2. **Import a brand guide** (optional): choose the client's PDF brand guide or an image of it, or type their website,
   and press **Read it with Claude**. In about a minute Claude fills in the colours, fonts, end screen and tone of
   voice, cuts the logo and the mark out of the guide, and lists what to check. Nothing is saved yet.
3. **Check and adjust**: colour pickers (with a contrast check), Google Fonts (search, or upload the client's font
   files), logos (light for dark backgrounds, dark for light ones, the mark), an optional background image, caption
   keywords, the end screen lines and call to action, and the tone of voice Claude writes in. The preview on the
   right shows a real caption, card, takeover, lower-third and end screen as you change things.
4. **Save.** **Delete** moves a kit to the Bin; videos that used it show the default look until you pick another brand.

Fonts: Google Fonts are free (OFL). Uploaded fonts must be licensed for video by the client.

## A video for a client

- **New** starts with **Who is this video for?**: your brand, a client, or **Add a client**. Claude then plans the
  video in that client's voice and ends it with their call to action; the end screen uses their lines and logo.
- In the editor, the brand chip in the header (short-form) or the brand menu in the top bar (long-form) switches the
  brand; the end screen follows (it asks first if you changed its lines). Undo works.
- **Open** has a client filter, and client videos carry the client's name on their thumbnail.
- Renders go to `06. Renders/<Client>/<format>/`; default videos stay in `06. Renders/<format>/`.

## AI studio

**AI studio** in the header opens a panel on the left, in short-form and long-form (in long-form, videos are
picked in Finder and linked, not copied, and an insert can be undone with ⌘Z until you save):
1. **Media bin:** add the videos to build from (inserts, testimonials, B-roll, other takes). Each one is transcribed
   and looked through once.
2. **Ask:** say what you want ("use these videos to make a 20-second trailer, end on the testimonial"), pick the
   length, title cards on or off, and music (from the team library in `05. Music`, or upload a track).
3. Claude picks the moments and says what it made and why; the clip is built in the video's format and brand.
   **Make another**, **Change it** ("faster, end on the testimonial"), **Download**, **Add at playhead** to lay it over
   the video (its sound plays and the speaker drops out), or **Insert at playhead**: the video pauses while the clip
   plays and everything after moves later (the base edit is re-rendered; the clip shows as **Insert** on the Video
   track, and deleting it there takes it out again). Put the playhead in a gap between cards and takeovers.


## Post it (new)

**Posts** in the header opens **Post it** for the open video (short-form or long-form); **Prepare posts** appears when a
render finishes.
- Choose where it goes (Instagram, TikTok, YouTube, Facebook, LinkedIn, X, Threads, Pinterest, Google Business,
  Bluesky). Each video's format picks sensible ones first.
- Press **Write with Claude**: Claude writes each platform's post in the brand's voice, with live character counts.
  **Rewrite** redoes one platform.
- Pause the video on a good frame for the **cover**.
- **Download post pack**: the video, the cover, and a text file per platform.
- Client videos: hand the pack to the client.
- **Schedule** (default-brand videos, once rendered): each channel gets a suggested time from your brand's usual slots, or
  your own. Press **Schedule N posts**.

## Calendar (new)

**Calendar** in the header shows every scheduled and live post: week, month or list.
- Drag a card to move it; click it for its posts, **Post now**, **Move** or **Cancel**.
- Until the developer connects the channels, a post whose time has come is **due**: the team gets an email with the
  post's text, the calendar shows it, and you post it by hand and press **Mark posted**. Failed posts are emailed too.
- **Email notifications** (Social settings): who gets them, the mail server, and **Send a test email**.
- **Social settings** (in the calendar): your brand's channels and handles, usual posting times, standard hashtags
  and time zone.
- **Connections:** once the developer has added a platform's app keys (Social settings → **App keys**), **Connect**
  signs in to your brand's account on that platform, and its posts then go out on their own at their time.
  **Use the test platform** tries all of this with no real accounts.
- **TikTok** sends each video to the TikTok app's inbox by default: the team is emailed, and someone taps Post on the
  phone. **LinkedIn** posts as the company page or a person's profile; its sign-in lasts 60 days, and Social settings
  says when to connect it again.

**On a Mac, posts go out only while Studio AI is open** on the Mac that scheduled them (the planner lives in that
Mac's `08. Planner` folder). Keep it open on one Mac that schedules your brand's posts,
which is always on. A post whose time passed while Studio AI was closed goes out as soon as it's opened again.

## Results (new)

**Results** (in the calendar's header) shows how your brand's posts do. The numbers are pulled from each platform an
hour after posting, at 6 and 24 hours, then daily for a month and weekly to three months; **Update now** pulls them
straight away.
- Views, likes, comments, shares, watch time and engagement, for 7, 30 or 90 days or everything, for one channel or
  format or all.
- Views gained each day, by channel. Each channel's numbers. Top videos. What works: views per post by format and by
  length.
- **Best times to post:** for each channel, the weekday and hour whose posts got the most views in their first day
  (once a channel has 4 posts). **+** adds one to that channel's usual times.
- Each live post's numbers also show in the calendar. Posts marked as posted by hand have no numbers.

## Folders

- `01. Short-form/`: Reels, Feed, Square and short Landscape videos.
- `02. Long-form/`: 60+ minute YouTube and webinar videos.
- `03. Brands/`: one folder per brand; `default` is the default look. See `03. Brands/README.md`.
- `05. Music/`: music beds for AI studio clips (licensed tracks only; not in git or the package).
- `04. Installation/`: installer, setup check, install guide, and `Build Studio package.sh` (makes the team zip).
- `08. Planner/`: the social planner's settings, scheduled posts, covers and results (on this Mac only; not in git or
  the package).
