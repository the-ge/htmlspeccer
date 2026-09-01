# htmlspeccer

## Summary

This repository generates JSON and YAML files from the [WHATWG HTML Living Standard](https://html.spec.whatwg.org/) and [Accessible Rich Internet Applications (WAI-ARIA)](https://w3c.github.io/aria/) websites. It queries the `Last-Modified` header to find when was each source file updated.

This repository was originally a fork of [Tawesoft](https://github.com/tawesoft)'s [**html5spec** repository](https://github.com/tawesoft/html5spec/), which was archived by its owner on Nov 3, 2025. 

## Source Data Last Updated

| Page | Last Updated |
| :--- | :--- |
| [Semantics, structure, and APIs of HTML documents](https://html.spec.whatwg.org/multipage/dom.html) | <!-- DOM_LAST_UPDATED:START -->Tue, 01 Sep 2026 14:39:10 GMT<!-- DOM_LAST_UPDATED:END --> |
| [WHATWG HTML Living Standard Index Page](https://html.spec.whatwg.org/multipage/indices.html) | <!-- INDICES_LAST_UPDATED:START -->Tue, 01 Sep 2026 14:39:12 GMT<!-- INDICES_LAST_UPDATED:END --> |
| [The input element](https://html.spec.whatwg.org/multipage/input.html) | <!-- INPUT_LAST_UPDATED:START -->Tue, 01 Sep 2026 14:39:11 GMT<!-- INPUT_LAST_UPDATED:END --> |
| [The HTML syntax](https://html.spec.whatwg.org/multipage/syntax.html) | <!-- SYNTAX_LAST_UPDATED:START -->Tue, 01 Sep 2026 14:39:11 GMT<!-- SYNTAX_LAST_UPDATED:END --> |
| [Accessible Rich Internet Applications (WAI-ARIA)](https://w3c.github.io/aria/) | <!-- ARIA_LAST_UPDATED:START -->Sat, 29 Aug 2026 17:28:15 GMT<!-- ARIA_LAST_UPDATED:END --> |

> [!CAUTION]
> **I do not intend to keep any backwards compatibility whatsoever with the old [**html5spec** repository](https://github.com/tawesoft/html5spec/).** If you are relying on the old repository conventions, your best bet would be to fork it yourself. Sorry about that ¯\\\_\_(ツ)\_\_/¯.
> 
> Also, aside from the inherent brittle nature of trying to add structure to data from non-structured data sources, the data structures for this repository's own end files are still work in progress, so do not rely on hardwired keys or data types.

## Source data issues

If the following issues are not crossed of, they are not solved by the updates shown above and they need specific workarounds to overcome their effects.

| Location | Description | Last checked at |
| :--- | :--- | :--- |
| [**`controls`**](https://html.spec.whatwg.org/multipage/indices.html#attributes-3:attr-media-controls) table row | the "Element(s)" cell is missing a `;` between the `video` and `img` `<code>` elements. | <!-- INDICES_LAST_UPDATED:START -->Tue, 01 Sep 2026 14:39:12 GMT<!-- INDICES_LAST_UPDATED:END --> |

## Original README (minus the "Alternatives" section)

> This repository contains Python code that generates machine-readable JSON
> from the [WHATWG HTML Living Standard](https://html.spec.whatwg.org/multipage/)
> and [Accessible Rich Internet Applications (WAI-ARIA)](https://w3c.github.io/aria/)
> 
> This is a work-in-progress and incomplete without a stable format.
> Contributions are very welcome. Regardless, even in this undeveloped state,
> this project is still a good basis for many real-world applications.
> 
> Type `make` to download and parse the spec.
> 
> This repo currently contains a spec as of 2020, and only
> [small updates](https://github.com/tawesoft/html5spec/issues/6)
> are needed to support the spec as of December 2024.
> 
> 
> Scope & Mission Statement
> --------------------------------------------------------------------------------
> 
> Much of HTML5 depends on context and subtle semantics. Checking this may either
> be extremely computationally expensive, or express the intention of the author
> in a way that not even a human reader can validate for certain. Additionally,
> it is challenging to represent complex rules in a language-agnostic way.
> 
> This machine-readable specification will, therefore, always be incomplete.
> Sometimes the best we can practically do is provide human-readable hints in
> descriptions. Therefore, this machine-readable specification aims to assist a
> human author and catch obvious errors - but not replace the human author
> entirely.


