"""
Renders the AI-generated JSON content into full branded HTML, using the brand's
visual constants from brands.py. Plain string templates (.format()-based), matching
the pattern already used across the emailcreationskill templates — no templating
engine dependency.

Layout skeleton (identical for both types, per the brief):
  header module (logo) -> hero module (headline + CTA) -> body module (copy) -> footer
"""
import html

_LEGAL_BLOCK = """
<tr><td style="padding:32px 24px 0;font-family:Arial,sans-serif;font-size:12px;color:#666;line-height:1.6">
  <p><strong>PRIVACY</strong><br/>You will not be asked for any personally identifiable
  information. Reviews are attributed to your role, company size, and industry.
  Responses will be subject to the Linux Foundation&rsquo;s Privacy Policy, available at
  <a href="https://linuxfoundation.org/privacy" style="color:#666">https://linuxfoundation.org/privacy</a>.</p>
  <p><strong>VISIBILITY</strong><br/>The data we collect from this survey will be
  analyzed to produce an in-depth survey report that will be published on the Linux
  Foundation website. The dataset from this survey and instructions for its use will be
  made publicly available on the Linux Foundation&rsquo;s {data_host} account.</p>
  <p><strong>QUESTIONS</strong><br/>If you have questions regarding this survey, please
  email us at
  <a href="mailto:research@linuxfoundation.org" style="color:#666">research@linuxfoundation.org</a>.</p>
</td></tr>
"""

_SHARE_BLOCK = """
<tr><td style="padding:16px 24px 0;font-family:Arial,sans-serif;font-size:13px;text-align:center">
  {share_line_html}
  <a href="#" style="color:{cta_color};text-decoration:none;font-weight:bold;margin-right:16px">SHARE ON X</a>
  <a href="#" style="color:{cta_color};text-decoration:none;font-weight:bold">SHARE ON LINKEDIN</a>
</td></tr>
"""

_EXTRA_BLOCKS = {
    "next_steps": """
<tr><td style="padding:24px 24px 0;font-family:Arial,sans-serif;font-size:14px;color:#222">
  <p><strong>Next Steps</strong></p>
  <ul>{next_steps_items}</ul>
</td></tr>
""",
    "about_org": """
<tr><td style="padding:16px 24px 0;font-family:Arial,sans-serif;font-size:13px;color:#555">
  <p><strong>About {sender_name}</strong><br/>{about_text}</p>
</td></tr>
""",
}

_TEMPLATE = """<!DOCTYPE html>
<html>
<body style="margin:0;padding:0;background:#f4f4f4">
<table role="presentation" width="640" align="center" cellpadding="0" cellspacing="0"
       style="background:#ffffff;font-family:Arial,sans-serif;max-width:640px">

  <!-- Header -->
  <tr><td style="padding:20px 24px;text-align:left;border-bottom:1px solid #eee">
    <span style="font-size:14px;font-weight:bold;color:#222">{header_logo_text}</span>
  </td></tr>

  <!-- Hero -->
  <tr><td style="background:{hero_accent};padding:40px 32px;color:#ffffff">
    {hero_image_html}
    <div style="font-size:24px;font-weight:bold;line-height:1.3;margin-bottom:24px">{hero_headline}</div>
    <a href="{promoted_url}" style="display:inline-block;background:{cta_color};color:#ffffff;
       padding:12px 28px;border-radius:6px;text-decoration:none;font-weight:bold;letter-spacing:0.5px">
      {cta_text}
    </a>
  </td></tr>

  <!-- Body -->
  <tr><td style="padding:32px 24px;font-family:Arial,sans-serif;font-size:15px;color:#222;line-height:1.6">
    {body_html}
  </td></tr>
  {extra_blocks_html}
  {legal_or_share_html}

  <!-- Footer -->
  <tr><td style="padding:32px 24px;font-family:Arial,sans-serif;font-size:12px;color:#888">
    Sent by {sender_name} &middot; {sender_address}<br/>
    <a href="#" style="color:#888">Subscription Center</a>
  </td></tr>
</table>
</body>
</html>"""


def render_body_fragment(generated: dict) -> str:
    """Body-only HTML (paragraphs + optional bullets + incentive line), with no
    header/hero/footer wrapper. Used to PATCH just the body widget of a cloned
    HubSpot email while leaving its header/footer sections untouched."""
    paragraphs = generated.get("body_paragraphs") or []
    body_parts = [f"<p style='margin:0 0 14px'>{html.escape(p)}</p>" for p in paragraphs]

    if generated.get("use_bullets") and generated.get("bullets"):
        items = "".join(f"<li style='margin-bottom:8px'>{html.escape(b)}</li>" for b in generated["bullets"])
        body_parts.append(f"<ul style='padding-left:20px;margin:0'>{items}</ul>")

    impact_sentence = generated.get("impact_sentence") or ""
    if impact_sentence:
        body_parts.append(f"<p style='margin:0 0 14px;font-weight:bold'>{html.escape(impact_sentence)}</p>")

    incentive = generated.get("incentive") or ""
    if incentive:
        body_parts.append(
            f"<p style='margin:20px 0 0;font-size:12px;color:#666'>{html.escape(incentive)}</p>"
        )

    share_line = generated.get("share_line") or ""
    if share_line:
        body_parts.append(f"<p style='margin:16px 0 0;font-weight:bold'>{html.escape(share_line)}</p>")

    return "".join(body_parts)


def render_email_html(*, generated: dict, brand: dict, email_type: str, promoted_url: str,
                      hero_image_url: str = "") -> str:
    paragraphs = generated.get("body_paragraphs") or []
    body_parts = [f"<p style='margin:0 0 14px'>{html.escape(p)}</p>" for p in paragraphs]

    if generated.get("use_bullets") and generated.get("bullets"):
        items = "".join(f"<li style='margin-bottom:8px'>{html.escape(b)}</li>" for b in generated["bullets"])
        body_parts.append(f"<ul style='padding-left:20px;margin:0'>{items}</ul>")

    impact_sentence = generated.get("impact_sentence") or ""
    if impact_sentence:
        body_parts.append(f"<p style='margin:0 0 14px;font-weight:bold'>{html.escape(impact_sentence)}</p>")

    incentive = generated.get("incentive") or ""
    if incentive:
        body_parts.append(
            f"<p style='margin:20px 0 0;font-size:12px;color:#666'>{html.escape(incentive)}</p>"
        )

    hero_image_html = (
        f"<img src='{html.escape(hero_image_url)}' alt='' style='max-width:100%;height:auto;"
        f"display:block;margin-bottom:20px;border-radius:4px' />"
        if hero_image_url else ""
    )

    extra_html = ""
    for block_key in brand.get("extra_blocks", []):
        template = _EXTRA_BLOCKS.get(block_key)
        if not template:
            continue
        if block_key == "next_steps":
            extra_html += template.format(next_steps_items="<li>Review the full report</li>")
        elif block_key == "about_org":
            extra_html += template.format(sender_name=brand["sender_name"], about_text="")

    if email_type == "survey":
        legal_or_share_html = _LEGAL_BLOCK.format(data_host=brand.get("data_host", ""))
    else:
        share_line = generated.get("share_line") or ""
        share_line_html = (
            f"<p style='margin:0 0 10px;font-weight:bold'>{html.escape(share_line)}</p>" if share_line else ""
        )
        legal_or_share_html = _SHARE_BLOCK.format(cta_color=brand["cta_color"], share_line_html=share_line_html)

    return _TEMPLATE.format(
        header_logo_text=html.escape(brand["header_logo_text"]),
        hero_accent=brand["hero_accent"],
        hero_image_html=hero_image_html,
        hero_headline=html.escape(generated.get("hero_headline", "")),
        cta_color=brand["cta_color"],
        cta_text=html.escape(generated.get("cta_text", "")),
        promoted_url=promoted_url,
        body_html="".join(body_parts),
        extra_blocks_html=extra_html,
        legal_or_share_html=legal_or_share_html,
        sender_name=html.escape(brand["sender_name"]),
        sender_address=html.escape(brand["sender_address"]),
    )
