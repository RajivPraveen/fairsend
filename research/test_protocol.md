# Hands-on session script (about 20 minutes)

Run FairSend locally (`fairsend app`) on the researcher's laptop with Ollama running. Think-aloud is encouraged. Note
anything confusing (wording, numbers, layout) in the observation log below. Don't guide participants to an answer.

| # | Task (read aloud) | Success looks like | Record |
|---|---|---|---|
| 1 | "Pick the route you normally use and the amount you usually send. Who gets the most money to your recipient?" | Finds the top row and reads the amount received | time, success Y/N, comments |
| 2 | "Find the service you or your family use now. How much less does your recipient get with it than with the best option?" | Finds their provider, states the difference | the difference stated `[est_saving_per_transfer]` |
| 3 | "What part of the cost is the fee, and what part is hidden in the exchange rate?" | Uses the chart or the markup column | Y/N |
| 4 | (If they have a past receipt) "Upload it, check the numbers, and tell me what the exchange rate cost you." Otherwise type in a recent transfer from memory or a banking app | Reads the "cost you X in markup" sentence | markup found `[receipt_markup]` |
| 5 | "Imagine tuition of $X is due in 3 weeks. Which option would get it there cheapest and on time?" | Uses tuition mode, reads the headline | Y/N |
| 6 | "Open My yearly savings with your usual pattern. What does it say?" | Reads the yearly figure | yearly saving `[est_yearly_saving]` |
| 7 | (Optional) "Set an alert for a rate you'd be happy with." | Creates an alert, sees the manage token | alert set Y/N `[set_alert]` |
| 8 | "Ask the assistant one question you've wondered about." | Gets a cited answer or an honest "I don't know" | question asked, helpful Y/N |

**Observation log:** task #, what happened, quote, severity (blocker / confusing / minor).

Standard closing: "Thanks. FairSend shows estimates from public data. Always check the provider's own quote before sending."
