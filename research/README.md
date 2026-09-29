# User research kit

Everything needed to run the before/after study with international students.

| File | Use |
|---|---|
| `consent.md` | Read or send before the pre-survey |
| `pre_survey.md` | Baseline survey (about 5 minutes). Paste into Google Forms, Microsoft Forms, or Qualtrics |
| `test_protocol.md` | Script for the 20-minute hands-on session |
| `post_survey.md` | Follow-up survey, sent right after the session and again at 4 weeks |
| `templates/pre.csv`, `templates/post.csv` | The column names `analyze.py` expects; rename your form export's columns to match |
| `analyze.py` | Produces the results table and `results.md` from the survey exports plus alert data |

## Running the study

1. Recruit participants (for example, an international student association or a class). Aim for 15 to 30.
2. Give each participant a random code such as `P07`. Only the code goes in the survey data, never names or emails.
3. Pre-survey, then the hands-on session using `test_protocol.md`, then the post-survey.
4. Participants who set a rate alert during the session use their own email. Alert retention is measured from the
   alert database by creation date; no link between alerts and survey answers is stored.
5. Four weeks later, send the short follow-up (post-survey Part C) and run:

```bash
python research/analyze.py --pre data/research/pre.csv --post data/research/post.csv \
    --study-start 2026-10-15 --weeks 4
```

Keep raw exports in `data/research/`. It is git-ignored along with the rest of `data/`, so participants' answers are never committed.
