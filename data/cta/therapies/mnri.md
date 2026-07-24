# MNRI Therapy CTA

Status: Active

Category: Therapy

CTA Type: Specific Therapy

Priority: Specific Therapy - MNRI

Match Rule:
- Category = Therapy
- Specific Therapy = MNRI

Description:
Display this CTA when the Understanding Node has confidently identified MNRI (Masgutova Neurosensorimotor Reflex Integration) as the specific therapy the user is asking about. Do not display this CTA for general therapy questions or when no specific therapy has been confidently identified.

Trigger Examples:

## Learning / Educational Questions
- What is MNRI?
- Explain MNRI.
- Tell me about MNRI.
- How does MNRI work?
- What is MNRI therapy?
- What does MNRI stand for?
- What does MNRI mean?
- Explain Masgutova Neurosensorimotor Reflex Integration.
- Tell me about Masgutova Method.
- Tell me about the Masgutova Reflex Integration Method.
- How does Masgutova Neurosensorimotor Reflex Integration work?
- What is reflex integration in MNRI?
- How is MNRI performed?
- What happens in an MNRI session?
- What techniques does MNRI use?
- Who created MNRI?
- What is the history of MNRI?
- What conditions does MNRI treat?
- How long does MNRI therapy take?
- Is MNRI safe?
- What age group is MNRI for?

## Suitability / Recommendation Questions
- Would MNRI help my child?
- Should we consider MNRI?
- Is MNRI right for my child?
- Could MNRI help with sensory issues?
- Is MNRI suitable for my child's condition?
- Would MNRI be beneficial for us?
- Do you recommend MNRI?
- Is MNRI worth trying?
- Help me navigate MNRI

## Comparison Questions
- MNRI vs Neurofeedback.
- How does MNRI compare to Feldenkrais?
- Is MNRI better than Vision Therapy?
- MNRI vs Tomatis Method.
- What's the difference between MNRI and Safe and Sound Protocol?
- How is MNRI different from other reflex therapies?

## Navigation Requests
- MNRI page.
- Read about MNRI.
- Learn more about MNRI.
- Show me the MNRI page.
- Open the MNRI page.
- Take me to MNRI.
- Go to MNRI.
- Show MNRI information.
- MNRI details.

Aliases:

## Alternate Names
- Masgutova Neurosensorimotor Reflex Integration
- Masgutova Method
- Masgutova Reflex Integration
- Masgutova Reflex Integration Method
- Neurosensorimotor Reflex Integration
- Svetlana Masgutova Method
- MNRI Method

## Common Misspellings
- MRNI
- Manri

- Mnri Therapy
- Masgutova Neuro Sensorimotor Reflex Integration

Related Topics:
- Primitive Reflexes
- Reflex Integration
- Sensorimotor Development
- Neurosensorimotor Development

Do NOT Trigger:

If the user is asking about therapies in general, or no specific therapy has been confidently identified, do not display the MNRI CTA. Use the Therapy Library CTA (data/cta/therapies/general.md) instead.

Examples:
- What therapies are available?
- Which therapy should I choose?
- What therapy is best for my child?
- Can you recommend a therapy?
- I'm confused about therapies.
- Tell me about therapies.
- Therapy library.
- Help me choose a therapy.

Also do not trigger when a different specific therapy has been identified, such as:
- Neurofeedback
- Arrowsmith Program
- Feldenkrais Method
- Vision Therapy
- Lynn Valley Optometry
- Safe and Sound Protocol (SSP)
- Tomatis Method
- Integrated Listening Therapy
- Nemechek Protocol
- Cellular Hydration
- Ayurveda
- Naturopathy
- Access Consciousness
- Jill Stowell Learning Centers

Fallback Rule:

If the Understanding Node is not confident that the specific therapy is MNRI:
- If the user's intent is related to therapies in general, display the Therapy Library CTA (data/cta/therapies/general.md).
- Otherwise, do not display any therapy CTA.

Output Label:

Learn More About MNRI

CTA:

https://manascience.webflow.io/post/mnri
