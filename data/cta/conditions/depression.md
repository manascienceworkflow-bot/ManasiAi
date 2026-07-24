# Depression CTA

Status: Active

Category: Condition

CTA Type: Individual Condition

Priority: Specific Condition

Match Rule:

Display this CTA ONLY when:
- Category = Condition
- Specific Condition = Depression
- Confidence = High

Do NOT display this CTA if:
- Specific Condition = None
- Confidence is Low or Medium.
- The user is asking about conditions in general.
- The user is asking which condition they may have.
- The user is asking for a diagnosis.
- Another specific condition has been identified.

Description:

Display this CTA only when the conversation is specifically about Depression.

Trigger Examples:

## Learning About Depression

- What is depression?
- Explain depression.
- Tell me about depression.
- What is depressive disorder?
- Explain depressive disorder.
- Tell me about depressive disorder.
- What is clinical depression?
- What is major depressive disorder?
- What is MDD?
- What causes depression?
- Why does depression happen?

## Symptoms

- What are the symptoms of depression?
- What are the signs of depression?
- What does depression feel like?
- How do I know if I have depression?
- How is depression diagnosed?
- How do doctors diagnose depression?
- Can depression be diagnosed?

## Understanding Depression

- Can children have depression?
- Can teenagers have depression?
- Can adults have depression?
- Can older adults have depression?
- Who can develop depression?
- What are the different types of depression?
- What triggers depression?
- How common is depression?
- Can depression be mild?
- Can depression be severe?
- What are the stages of depression?
- Is depression a mental health condition?
- Is depression a mood disorder?

## Daily Life

- How does depression affect learning?
- How does depression affect school?
- How does depression affect work?
- How does depression affect relationships?
- Can depression affect sleep?
- Can depression affect concentration?
- Can depression affect behaviour?
- Can depression affect emotions?
- Can depression affect motivation?
- Can depression affect memory?

## Recovery & Support

- Can depression improve?
- Is depression treatable?
- Can depression be cured?
- Can depression go away?
- Is depression permanent?
- Can depression be managed?
- What support is available for depression?
- Where can I learn more about depression?
- How can someone manage depression?
- What resources are available for depression?

## Personal Questions

- I think I have depression.
- I have depression.
- My child has depression.
- My teenager has depression.
- My child seems depressed.
- I've been feeling depressed lately.
- I feel depressed.
- I'm worried I have depression.
- I think my child has depression.

## Comparison Questions

- Depression vs Anxiety
- Depression vs ADHD
- Depression vs Autism
- Depression vs Bipolar Disorder
- Depression vs Burnout
- Is it depression or anxiety?
- Is it depression or ADHD?
- Is it depression or burnout?
- What's the difference between depression and anxiety?
- What's the difference between depression and bipolar disorder?

## Navigation Requests

- Show me depression.
- Open depression.
- Depression page.
- Depression article.
- Depression information.
- Read about depression.
- Learn more about depression.
- Depression details.
- Open the depression page.
- View depression.

Aliases:

- Depression
- Depressive Disorder
- Major Depressive Disorder
- Clinical Depression
- MDD

Related Topics:

- Mental Health
- Mood
- Sadness
- Emotional Wellbeing
- Emotional Regulation
- Motivation
- Sleep
- Concentration
- Memory
- Stress
- Anxiety
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
- Explore conditions.

Questions about other specific conditions:

- ADHD
- Autism
- Anxiety
- Dyslexia
- Dyspraxia
- Dysgraphia
- Dyscalculia
- OCD
- Tourette Syndrome
- Sensory Processing Disorder
- Speech Delay
- Developmental Delay
- Bipolar Disorder

Fallback Rule:

If the Understanding Node cannot confidently identify **Depression** as the specific condition,

DO NOT display this CTA.

Instead:

- If the user is asking about conditions in general → Display the Conditions Library CTA.
- Otherwise → Do not display any condition CTA.

Output Label:

Learn More About Depression

CTA:

https://manascience.webflow.io/conditions/depression
