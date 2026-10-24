# Personal analytics methodology

Analytics are scoped to the signed-in account and completed, manually tracked sessions. Session records are bucketed by their local completion date using the time zone sent by the browser. Private Mode sessions are never sent to the server and are excluded.

## Measures

- **Focus time and work blocks:** completed sessions other than the explicitly selected Break category.
- **Break time and break count:** completed sessions explicitly started as Break. Pauses are not counted as breaks because pause duration is not separately recorded.
- **Focus rhythm:** days with at least one completed work session divided by calendar days in the selected period.
- **Average focus per active day:** mean work time across days with completed work. Days without a session are excluded.
- **Daily variation:** population standard deviation of work minutes across active days. This describes variation and is not a grade.
- **Typical work block:** median completed work-session duration.
- **Self-rated focus:** mean of optional 1–5 ratings entered by the user when ending work sessions.
- **Distractions:** events explicitly logged by the user, also shown per hour of tracked work time for context.
- **Time composition:** the chart compares manually tracked focus time with explicitly tracked break time and shows the distribution of focus time across session types. These are time shares, not productivity scores.

The dashboard pairs these two donut charts with the period's focus/break trend, optional self-ratings, and self-logged distractions. A missing rating or an empty period is shown as missing/empty rather than estimated.

## Focus coins and Excel export

Coins are awarded once when a saved manual session is completed. The selected session category sets the rate per 15 tracked minutes: Coding and Assignment 15 coins; Creative 12; Learning and Research 10; Learning video 3; Break and Private Mode 0. Paused time is excluded by the session timer. These rates reward the user's selected activity category and timer duration; they do not assess quality, cursor movement, or attention. Private Mode stays client-only and cannot earn persisted coins.

The **session-history Excel** contains saved session category, task/outcome, status, start/end timestamps, tracked duration, optional self-rating, user-logged distraction count, and awarded account coins. It does not contain app-level activity.

The optional Windows companion creates a separate **app-activity Excel** only after the user separately consents to app tracking, pairs the companion, and explicitly starts screen recording. That workbook contains foreground executable names, sampled foreground start/end times, duration by interval and app, and estimated coins based on the selected session category. App activity stays in the companion's local database; it is not added to account analytics or account coins. See `desktop-companion.md` for the workflow and limits.

## Periods

Weekly analysis covers seven days through the selected date. Monthly analysis starts on the first day of the selected month and yearly analysis starts on January 1. The period controls allow reviewing past weeks, months, and years. Current periods end today; historical months and years cover the full selected period.

These are personal reflection measures from manual records. They do not observe screen contents, application activity, keystrokes, idle time, or infer concentration. They are not an HR ranking or an employment decision system.
