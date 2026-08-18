# Anxiety CTA

Status: Active

Category: Condition

CTA Type: Individual Condition

Priority: Specific Condition

Match Rule:

Display this CTA ONLY when:
- Category = Condition
- Specific Condition = Anxiety
- Confidence = High

Do NOT display this CTA if:
- Specific Condition = None
- Confidence is Low or Medium.
- The user is asking about conditions in general.
- The user is asking which condition they may have.
- The user is asking for a diagnosis.
- Another specific condition has been identified.

Description:

Display this CTA only when the conversation is specifically about Anxiety.

Trigger Examples:

## Learning About Anxiety

- What is anxiety?
- Explain anxiety.
- Tell me about anxiety.
- What is an anxiety disorder?
- Explain anxiety disorder.
- Tell me about anxiety disorders.
- What is generalized anxiety disorder?
- What is GAD?
- What causes anxiety?
- Why does anxiety happen?

## Symptoms

- What are the symptoms of anxiety?
- What are the signs of anxiety?
- What does anxiety feel like?
- How do I know if I have anxiety?
- How is anxiety diagnosed?
- How do doctors diagnose anxiety?
- Can anxiety be diagnosed?

## Understanding Anxiety

- Can children have anxiety?
- Can adults have anxiety?
- Can teenagers have anxiety?
- Can toddlers have anxiety?
- Can older adults have anxiety?
- Who can develop anxiety?
- What are the different types of anxiety?
- What triggers anxiety?
- How common is anxiety?
- Can anxiety be mild?
- Can anxiety be severe?
- What are the levels of anxiety?

## Daily Life

- How does anxiety affect learning?
- How does anxiety affect children?
- How does anxiety affect adults?
- Can anxiety affect school performance?
- Can anxiety affect concentration?
- Can anxiety affect sleep?
- Can anxiety affect behaviour?
- Can anxiety affect emotions?

## Recovery & Support

- Can anxiety improve?
- Is anxiety treatable?
- Can anxiety be cured?
- Can anxiety go away?
- Is anxiety permanent?
- Can anxiety be managed?
- What support is available for anxiety?
- Where can I learn more about anxiety?

## Personal Questions

- I think I have anxiety.
- I have anxiety.
- My child has anxiety.
- My child seems anxious.
- I feel anxious all the time.
- I'm worried I have anxiety.
- I think my child has anxiety.

## Comparison Questions

- Anxiety vs ADHD
- Anxiety vs Autism
- Anxiety vs OCD
- Anxiety vs Depression
- Is it anxiety or ADHD?
- Is it anxiety or autism?
- What's the difference between anxiety and ADHD?
- What's the difference between anxiety and OCD?

## Navigation Requests

- Show me anxiety.
- Open anxiety.
- Anxiety page.
- Anxiety article.
- Anxiety information.
- Read about anxiety.
- Learn more about anxiety.
- Anxiety details.

Aliases:

- Anxiety
- Anxiety Disorder
- Anxiety Disorders
- GAD
- Generalized Anxiety Disorder

Related Topics:

- Stress
- Worry
- Emotional Regulation
- Mental Health
- Sleep
- Neuroplasticity

Do NOT Trigger:

General condition questions:

- What conditions do you cover?
- Tell me about conditions.
- Browse conditions.
- Show all conditions.
- Which condition could this be?
- What condition might my child have?
- Help me understand possible conditions.
- Can you diagnose me?
- I think I have something.
- I'm not sure what condition this is.

Questions about other conditions:

- ADHD
- Autism
- Dyslexia
- Dyspraxia
- Dysgraphia
- Dyscalculia
- OCD
- Tourette Syndrome
- Sensory Processing Disorder
- Speech Delay
- Developmental Delay

Fallback Rule:

If the Understanding Node cannot confidently identify Anxiety as the specific condition,

DO NOT display this CTA.

Instead:

- If the user is asking about conditions in general → Display the Conditions Library CTA.
- Otherwise → Do not display any condition CTA.

Output Label:

Learn More About Anxiety

CTA:

https://manascience.webflow.io/conditions/anxiety
