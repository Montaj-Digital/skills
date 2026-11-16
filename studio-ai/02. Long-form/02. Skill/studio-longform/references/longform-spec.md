# longform.json spec

All times are seconds on the EDITED timeline (after cuts), 2 decimals.

```json
{
  "version": 1,
  "title": "SFH AI Workshop",
  "duration": 3912.4,
  "fps": 30,
  "size": [1920, 1080],
  "source": "raw/workshop.mp4",
  "edl": "work/edl.json",
  "captions": { "on": true, "style": "words", "size": 54, "bottom": 120 },
  "chapters": [ { "title": "Welcome and agenda", "start": 0.0, "end": 212.4 } ],
  "lowerThirds": [ { "t": 3.2, "dur": 4.5, "title": "Alex Example", "sub": "Founder, Example Co" } ],
  "cards": [
    { "type": "keypoint", "t": 95.1, "dur": 7, "title": "Start with one workflow", "body": "Automate one task end to end before adding more." },
    { "type": "stat", "t": 301.0, "dur": 6, "value": "70%", "label": "of admin time can be automated" },
    { "type": "list", "t": 640.5, "dur": 9, "title": "Three tools to try", "items": ["Claude", "Zapier", "n8n"] }
  ],
  "endcard": { "duration": 6, "lines": [ {"text": "Follow"}, {"text": "for more", "bold": true} ] }
}
```

## brand (Studio AI)

`"brand": "<id>"` uses a client brand kit (`03. Brands/<id>/brand.json`) for the graphics' colours and fonts and the end
screen logo, in the editor preview and the render. Leave it out for the default look. New projects take the end screen
lines and Claude's tone of voice from the kit.

## Card types (Phase 1)

| type | fields | limits |
| --- | --- | --- |
| `keypoint` | `title`, `body` | title <= 6 words, body <= 14 words |
| `stat` | `value`, `label` | value short ("70%", "3x", "$2M"), label <= 8 words |
| `list` | `title`, `items[]` | 3-5 items, each <= 5 words |

Every card: `t` (start), `dur` (5-9 s), optional `pos` (left|center|right), `anim` (slide|fade|pop|none) and a free position `x`,`y` (top-left, 1920x1080 px; overrides `pos`; set by hand in the editor). Lower-thirds: `t`, `dur` (4-5 s), `title`, optional `sub`.

## Rules checked after planning

- `t` and `t + dur` stay inside the chapter that the item belongs to.
- No two cards overlap; a card never overlaps a lower-third; at least 20 s between cards; at most one card per 60 s.
- Chapters are contiguous, the first starts at 0, the last ends at `duration`.
- Chapters are at least 10 s long.

## Redactions (blur / pixelate / black box over the picture)

```json
"redactions": [ { "t": 120.0, "dur": 8, "type": "blur", "strength": 28, "w": 480, "h": 270, "track": true,
                  "keys": [ { "dt": 0, "x": 720, "y": 405 }, { "dt": 4, "x": 900, "y": 405 } ] } ]
```
`type` blur | pixel | box. Frame pixels at 1920x1080, x and y are the top-left corner. `keys` times are seconds after `t`;
with more than one key the region moves in a straight line between them. Planning never adds these: a person places them.
