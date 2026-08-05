# -*- coding: utf-8 -*-
"""One Search Console day for one site: the traffic curve.

Everything else in this module stores a 28-day snapshot — useful to know
where a site stands today, useless to answer "is it going up?". Google
keeps 16 months of daily figures; storing them turns a static number into
a curve an agency can show a client month after month.

Rows are keyed on (site, date) and re-written on every sync, because
Search Console revises the last three days as its data consolidates.
"""
from odoo import api, fields, models


class SeoSearchPerformance(models.Model):
    _name = "seo.search.performance"
    _description = "Daily Search Console performance"
    _order = "date desc, site_id"
    _rec_name = "date"

    _unique_site_day = models.Constraint(
        "UNIQUE(site_id, date)",
        "This site already has a row for that day.")

    site_id = fields.Many2one(
        "seo.site", string="Site", required=True,
        ondelete="cascade", index=True)
    date = fields.Date(string="Date", required=True, index=True)
    # Clicks and impressions are counts: summing them over a month is the
    # figure a client wants. CTR and position are ratios and ranks — they
    # must be averaged, or a graph adds up rankings into nonsense.
    clicks = fields.Integer(string="Clicks", readonly=True)
    impressions = fields.Integer(string="Impressions", readonly=True)
    ctr = fields.Float(
        string="CTR (%)", digits=(6, 2), readonly=True, aggregator="avg",
        help="Clicks divided by impressions. Over a group this is the "
             "weighted ratio of the totals, not the mean of daily rates "
             "— see _read_group below.")
    position = fields.Float(
        string="Avg position", digits=(6, 1), readonly=True,
        aggregator="avg")

    # A rate is not the mean of daily rates. Averaging them gives a day
    # with 2 impressions the same weight as a day with 300, which is how
    # a real 12.07% month showed up as 8.42% in the pivot. Odoo only
    # offers sum/avg/min/max as aggregators, so the honest figure has to
    # be recomputed from the summed parts after grouping.
    _WEIGHTED = {"ctr": ("clicks", "impressions", 100.0)}

    @api.model
    def _read_group(self, domain, groupby=(), aggregates=(), having=(),
                    offset=0, limit=None, order=None):
        """Recompute rate aggregates as weighted ratios, not plain means.

        Only aggregates spelled `<rate>:avg` are touched, and the parts
        they need are appended to the query then dropped from the result,
        so every caller — pivot, graph, export, custom code — gets the
        same corrected figure without asking for it.
        """
        aggregates = list(aggregates)
        extra = []
        fixes = []  # (index of the rate, index of numerator, denominator, factor)
        for i, spec in enumerate(aggregates):
            name = spec.split(":")[0]
            rate = self._WEIGHTED.get(name)
            if not rate or not spec.endswith(":avg"):
                continue
            num, den, factor = rate
            positions = []
            for part in (num, den):
                spec_part = "%s:sum" % part
                if spec_part not in aggregates:
                    aggregates.append(spec_part)
                    extra.append(spec_part)
                positions.append(aggregates.index(spec_part))
            fixes.append((i, positions[0], positions[1], factor))

        rows = super()._read_group(
            domain, groupby, aggregates, having, offset, limit, order)
        if not fixes:
            return rows

        shift = len(groupby)
        drop = sorted(
            (shift + aggregates.index(spec) for spec in extra), reverse=True)
        fixed = []
        for row in rows:
            values = list(row)
            for rate_i, num_i, den_i, factor in fixes:
                den = values[shift + den_i] or 0
                num = values[shift + num_i] or 0
                values[shift + rate_i] = (factor * num / den) if den else 0.0
            for index in drop:
                del values[index]
            fixed.append(tuple(values))
        return fixed

    def _store_rows(self, site, rows):
        """Upsert daily rows for one site. Returns how many days are new.

        Google restates recent days as data consolidates, so existing rows
        are updated rather than skipped — the last three days would stay
        wrong forever otherwise.
        """
        existing = {
            row.date.isoformat(): row
            for row in self.search([("site_id", "=", site.id)])
        }
        created = 0
        to_create = []
        for row in rows:
            day = row["key"]
            vals = {
                "clicks": row["clicks"],
                "impressions": row["impressions"],
                "ctr": row["ctr"],
                "position": row["position"],
            }
            known = existing.get(day)
            if known:
                known.write(vals)
            else:
                to_create.append(dict(vals, site_id=site.id, date=day))
                created += 1
        if to_create:
            self.create(to_create)
        return created
