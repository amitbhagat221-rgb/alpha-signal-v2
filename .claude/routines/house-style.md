# House style: explain it like I'm five

The CEO reads you on a phone, between other things. He is smart, but he does not want to decode you. Jargon slows
his decisions. Write so that a clever friend who does not work in finance or software would understand it the first
time.

## How to write
- Short sentences: ten to fifteen words. One idea each.
- Short paragraphs: one to three sentences.
- Everyday words. Say "prices fell" and not "the index de-rated". Say "foreign investors are selling" and not
  "FPI outflows". Say "our scheduled job" and not "the cron".
- If a technical term is truly needed, explain it in a few words the first time, in brackets.
- Use one everyday comparison when it makes the point land ("think of it like ..."). One, not three.
- Few numbers. Pick the one or two that matter and say what they mean. The rest belong in the details.
- Say what it means for him and what he should do. If the answer is "nothing, just know this", say so.
- Do not hedge every sentence. Say what you think and how sure you are, once.

## The plain-words block (`eli5`)
Every memo starts with it. It must stand alone: he should be able to decide from it without reading further.
- `what`: What is happening? Two or three short sentences.
- `why`: Why does it matter to him or to the fund?
- `do`: What should he do? Name the action, or say that nothing is needed.
- `remember`: The one line to remember.
- `like` (optional): the everyday comparison.

The server checks the plain-words block, the headline and everything addressed to the CEO: it sends a memo back if
it finds trade jargon, code names such as `book_to_price`, or a sentence longer than about twenty-five words. The
technical detail still has a home in the detail fields and in `evidence`.
