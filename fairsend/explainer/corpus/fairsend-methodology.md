---
id: fairsend-methodology
title: "How FairSend measures the true cost of a transfer"
publisher: FairSend project
url: fairsend/explainer/corpus/fairsend-methodology.md
license: Project documentation
retrieved: 2026-09-29
---

## Two parts of the cost: fee and exchange-rate markup
Sending money abroad usually costs you in two ways. The first is the upfront transfer fee, which is shown as a separate charge. The second is the exchange-rate markup: the provider converts your money at a rate that is less favourable than the mid-market rate and keeps the difference. The markup is not listed as a fee, so it is easy to miss. FairSend adds the two together to show the true total cost of a transfer, following the same idea as the World Bank, which measures total cost as the fee plus the foreign exchange (FX) margin.

## What the mid-market rate is
The mid-market rate is the midpoint between the buying and selling prices of a currency in wholesale markets. It is sometimes called the interbank rate, and it is the benchmark for a "fair" conversion with no markup. FairSend gets the mid-market rate from the European Central Bank's daily reference rates, accessed through the free Frankfurter service, for the roughly 30 currencies the ECB publishes. For currencies the ECB does not publish (for example NGN, PKR, BDT or KES), FairSend uses an open daily currency-rate dataset as a fallback. If neither is available, it falls back to the interbank rate the World Bank recorded for that corridor in its latest survey. Reference rates are published once a day, so they can differ slightly from the rate at the exact moment you send.

## How FairSend calculates the exchange-rate markup
The exchange-rate markup (also called the FX margin, spread, or mark-up) is how much worse the provider's rate is than the mid-market rate, expressed as a percentage:

markup % = (mid-market rate - provider's rate) / mid-market rate x 100

For example, if the mid-market rate is 1 USD = 100 units of the receiving currency and the provider gives you 98, the markup is (100 - 98) / 100 = 2 percent. The markup cost in money is the amount being converted multiplied by the markup percentage. On 1,000 USD converted, a 2 percent markup costs 20 USD.

## How FairSend calculates total cost
FairSend's total cost is:

total cost = fee + markup cost

where the markup cost is the amount converted times the markup percentage. The total cost can also be shown as a percentage of the amount you send, which makes providers comparable. For example, a 5 USD fee plus a 2 percent markup on 1,000 USD gives a total cost of 5 + 20 = 25 USD, or 2.5 percent. FairSend also shows how much of the total cost is "hidden" in the exchange rate rather than in the fee.

## Why a zero-fee transfer can still be expensive
A transfer advertised as "zero fee" or "no fee" is not necessarily free. The provider can still earn money by giving you an exchange rate below the mid-market rate, so the cost moves from the fee into the rate. A no-fee transfer with a 3 percent markup costs more than a transfer with a small fee and a 0.5 percent markup. To compare offers fairly, look at the total cost (fee plus markup), or simply at how much the recipient will receive for the same amount sent. U.S. rules require providers to disclose the exchange rate and the "Total to Recipient" before you pay, which makes this comparison possible.

## What a guaranteed rate means
In general, a "guaranteed" or "locked" exchange rate means the provider fixes the rate at the time it gives you a quote, so the amount the recipient gets will not change if the market moves before the transfer is completed, usually as long as you pay within a stated time window. A guaranteed rate protects you from rate movements during that window, but it says nothing about how large the markup is: a guaranteed rate can still be well below the mid-market rate. Terms differ between providers, so check how long the guarantee lasts.

## How FairSend uses World Bank price data
FairSend uses the World Bank's Remittance Prices Worldwide (RPW) data to show typical costs on a route. RPW prices are periodic snapshots collected by mystery shopping and labelled by quarter, not live quotes. They are collected for sending about $200 and about $500 (or the local-currency equivalent), so costs for other amounts can differ, especially because a fixed fee weighs more heavily on a small transfer. When FairSend estimates a provider's rate today, it applies the markup the World Bank observed for that product to today's mid-market rate, because the markup is the more stable part of a provider's pricing while the rate itself moves daily.

## Limits of FairSend's numbers
FairSend's figures are estimates for information and comparison. They are not quotes and not financial advice. The actual fee and rate come from the provider at the time you send, and U.S. law requires providers to show them to you before you pay. Fees charged by the recipient's bank and foreign taxes may also reduce the amount received and may not be included in a provider's quote.
