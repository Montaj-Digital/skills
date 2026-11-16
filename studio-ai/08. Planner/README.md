# Planner

your brand's social planner on this Mac, written by Studio AI's Post it, Calendar, Social settings and Results:
- `social.json`: channels, usual times, hashtags, time zone, email notifications, connection choices;
- `posts/` with each post's cover in `covers/`;
- `results/`: each live post's numbers over time;
- `connections.json`: which channels are connected (no secrets; sign-ins and app keys are in the Keychain).

This is the team's data: it stays out of git and the package, and an update never copies over it. On the team portal it
lives in the team's storage instead (`teams/<team>/Planner/`).
