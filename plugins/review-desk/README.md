# review-desk

Review a pull request as a conversation instead of a diff.

A diff tells you what changed. It gives you no way to ask **why**, which is most
of what a reviewer actually wants to do — so requests get waved through, or
answered with instructions, and neither of those is judgement.

This publishes a pull request as a page: what is needed to judge it, a
conversation with Claude held inside it, and a decision recorded at the end.
The discussion then comes back and is written into the pull request, so the
reasoning lives with the code rather than evaporating.

## Use

    /review-desk 12          # publish it, hand over the link
    /review-collect 12       # read the discussion back, write it in, merge

## Worth knowing

The Claude answering inside the page is a **fresh call** that can see the pull
request and the conversation and nothing else. It cannot run tests or read the
wider repository. The page says so, and so should you when you hand over the
link.

The reviewer pays for those calls and is asked for consent on the first one.

The page needs the `sample` and `db` capabilities. Without `db` the conversation
still happens but nothing comes back, which defeats the point.

## Why it exists

Built for a reviewer who reads pull requests on an iPad, away from any terminal,
and who needs to approve intent before code exists rather than audit code after
it arrives.
