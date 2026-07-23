---
layout: single
title: "Publications"
permalink: /publications/
author_profile: true
---

{% include base_path %}

{% assign pubs = site.data.publications %}
{% assign total = pubs | size %}

<p class="pub-intro">
  {{ total }} publications, imported from
  <a href="https://openalex.org/">OpenAlex</a>,
  <a href="https://www.semanticscholar.org/">Semantic Scholar</a> and
  <a href="https://dblp.org/pid/136/8659.html">DBLP</a>.
  Also on <a href="https://scholar.google.de/citations?user=rDKEGNgAAAAJ&hl=en">Google Scholar</a>
  and <a href="https://orcid.org/0000-0002-8289-388X">ORCID</a>.
</p>

<div class="pub-controls">
  <input type="search" id="pub-search" class="pub-search"
         placeholder="Search title, author, venue or year…" aria-label="Search publications">
  <div class="pub-filters" id="pub-filters">
    <button class="pub-filter is-active" data-type="all">All</button>
    <button class="pub-filter" data-type="journal">Journal</button>
    <button class="pub-filter" data-type="conference">Conference</button>
    <button class="pub-filter" data-type="workshop">Workshop</button>
    <button class="pub-filter" data-type="preprint">Preprint</button>
    <button class="pub-filter" data-type="book-chapter">Book chapter</button>
    <button class="pub-filter" data-type="thesis">Thesis</button>
    <button class="pub-filter" data-type="poster">Poster</button>
  </div>
</div>

<p class="pub-count" id="pub-count"></p>

{% assign by_year = pubs | group_by: "year" | sort: "name" | reverse %}
{% for group in by_year %}
  <section class="pub-year-block" data-year="{{ group.name }}">
    {% if group.name and group.name != "" %}
    <h2 class="pub-year">{{ group.name }}</h2>
    {% else %}
    <h2 class="pub-year">In press / undated</h2>
    {% endif %}
    <ul class="pub-list">
      {% for p in group.items %}
      {% assign n_authors = p.authors | size %}
      <li class="pub-item" data-type="{{ p.type }}"
          data-search="{{ p.title | downcase | escape }} {{ p.authors | join: ' ' | downcase | escape }} {{ p.venue | downcase | escape }} {{ p.year }}">
        <span class="pub-type pub-type--{{ p.type }}">{{ p.type | replace: '-', ' ' }}</span>
        <div class="pub-body">
          <div class="pub-title">{{ p.title }}{% if p.award %} <span class="pub-award">🏆 {{ p.award }}</span>{% endif %}</div>
          <div class="pub-meta">
            {% if p.authors %}
            {%- comment -%}
              Collapsed lists always keep his own name visible: leading authors,
              an ellipsis, then his entry, and a trailing ellipsis when he is not
              last. Find his position first.
            {%- endcomment -%}
            {%- assign yidx = -1 -%}
            {%- for a in p.authors -%}
              {%- if yidx == -1 and a contains 'Yimam' -%}{%- assign yidx = forloop.index0 -%}{%- endif -%}
            {%- endfor -%}
            {%- assign last_i = n_authors | minus: 1 -%}
            <span class="pub-authors">
              {%- if n_authors <= 4 -%}
                {%- for a in p.authors -%}
                  {%- if a contains 'Yimam' -%}<strong>{{ a }}</strong>{%- else -%}{{ a }}{%- endif -%}
                  {%- unless forloop.last %}, {% endunless -%}
                {%- endfor -%}
              {%- else -%}
                <span class="pub-authors__short">
                  {%- if yidx == -1 or yidx < 3 -%}
                    {%- for a in p.authors limit: 3 -%}
                      {%- if a contains 'Yimam' -%}<strong>{{ a }}</strong>{%- else -%}{{ a }}{%- endif -%}
                      {%- unless forloop.last %}, {% endunless -%}
                    {%- endfor -%} …
                  {%- else -%}
                    {%- for a in p.authors limit: 2 -%}{{ a }}{%- unless forloop.last %}, {% endunless -%}{%- endfor -%}
                    , …, <strong>{{ p.authors[yidx] }}</strong>
                    {%- if yidx < last_i -%}, …{%- endif -%}
                  {%- endif -%}
                </span>
                <span class="pub-authors__full" hidden>
                  {%- for a in p.authors -%}
                    {%- if a contains 'Yimam' -%}<strong>{{ a }}</strong>{%- else -%}{{ a }}{%- endif -%}
                    {%- unless forloop.last %}, {% endunless -%}
                  {%- endfor -%}
                </span>
                <button type="button" class="pub-authors__toggle"
                        aria-expanded="false">all {{ n_authors }}</button>
              {%- endif -%}
            </span>
            {% endif %}
            {% if p.venue %}<span class="pub-venue">{{ p.venue }}</span>{% endif %}
            <span class="pub-links">
              {% if p.pdf %}<a href="{{ p.pdf }}">PDF</a>{% endif %}
              {% if p.anthology %}<a href="{{ p.anthology }}">ACL</a>{% endif %}
              {% if p.doi_url %}<a href="{{ p.doi_url }}">DOI</a>{% endif %}
              {% if p.arxiv %}<a href="https://arxiv.org/abs/{{ p.arxiv }}">arXiv</a>{% endif %}
              {% if p.url and p.pdf == nil and p.doi_url == nil %}<a href="{{ p.url }}">Link</a>{% endif %}
            </span>
          </div>
        </div>
      </li>
      {% endfor %}
    </ul>
  </section>
{% endfor %}

<script>
(function () {
  var search  = document.getElementById('pub-search');
  var filters = document.getElementById('pub-filters');
  var counter = document.getElementById('pub-count');
  var items   = Array.prototype.slice.call(document.querySelectorAll('.pub-item'));
  var blocks  = Array.prototype.slice.call(document.querySelectorAll('.pub-year-block'));
  var type    = 'all';

  function apply() {
    var q = (search.value || '').trim().toLowerCase();
    var shown = 0;
    items.forEach(function (el) {
      var okType = type === 'all' || el.dataset.type === type;
      var okText = !q || (el.dataset.search || '').indexOf(q) !== -1;
      var visible = okType && okText;
      el.hidden = !visible;
      if (visible) shown++;
    });
    /* Hide a year heading when every entry under it is filtered out. */
    blocks.forEach(function (block) {
      var any = block.querySelectorAll('.pub-item:not([hidden])').length > 0;
      block.hidden = !any;
    });
    counter.textContent = shown + ' of ' + items.length + ' shown';
  }

  /* Long author lists show three names; the rest unfold in place on demand. */
  Array.prototype.forEach.call(document.querySelectorAll('.pub-authors__toggle'), function (b) {
    b.dataset.label = b.textContent;
  });

  document.addEventListener('click', function (e) {
    var btn = e.target.closest && e.target.closest('.pub-authors__toggle');
    if (!btn) return;
    var short = btn.parentNode.querySelector('.pub-authors__short');
    var full = btn.parentNode.querySelector('.pub-authors__full');
    if (!short || !full) return;
    var opening = full.hidden;
    full.hidden = !opening;
    short.hidden = opening;
    btn.setAttribute('aria-expanded', String(opening));
    btn.textContent = opening ? 'less' : btn.dataset.label;
  });

  search.addEventListener('input', apply);
  filters.addEventListener('click', function (e) {
    var btn = e.target.closest('.pub-filter');
    if (!btn) return;
    type = btn.dataset.type;
    filters.querySelectorAll('.pub-filter').forEach(function (b) {
      b.classList.toggle('is-active', b === btn);
    });
    apply();
  });

  apply();
})();
</script>
