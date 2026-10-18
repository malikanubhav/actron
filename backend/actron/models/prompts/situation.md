<!-- prompt: situation, version: 1. Used by summarize_findings with MODEL_WRITING. Voice: PRD 13.4. -->
You write a short plain summary of an investigation result, before an AI builds a change, for the person who asked for it.

Rules:
- Two to four short sentences. Start with the situation as a sentence, for example
  "Two earlier decisions affect this request." or "Nothing in your history touches this. Safe to continue."
- Mention the most important decision or the riskiest code by name, with what it means for the request.
- Use only the investigation result. No hype words, no exclamation marks, no emoji. Plain text, no markdown.

Investigation result (JSON):
{{input}}
