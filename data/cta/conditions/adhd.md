# ADHD CTA

Status: Active

Category: Condition

CTA Type: Individual Condition

Priority: Specific Condition

Match Rule:

Display this CTA ONLY when:
- Category = Condition
- Specific Condition = ADHD
- Confidence = High

Do NOT display this CTA if:
- Specific Condition = None
- Confidence is Low or Medium.
- The user is asking about conditions in general.
- The user is asking which condition they may have.
- The user is asking for a diagnosis.
- Another specific condition has been identified.

Description:

Display this CTA only when the conversation is specifically about ADHD (Attention-Deficit/Hyperactivity Disorder).

Trigger Examples:

## Learning About ADHD

- What is ADHD?
- Explain ADHD.
- Tell me about ADHD.
- What does ADHD stand for?
- Explain Attention Deficit Hyperactivity Disorder.
- Explain Attention Deficit Disorder.
- What causes ADHD?
- Why does ADHD happen?
- What is inattentive ADHD?
- What is hyperactive ADHD?
- What is combined type ADHD?
- What are the different types of ADHD?

## Symptoms

- What are the symptoms of ADHD?
- What are the signs of ADHD?
- How do I know if I have ADHD?
- How is ADHD diagnosed?
- How do doctors diagnose ADHD?
- Can ADHD be diagnosed?
- ADHD symptoms in adults.
- ADHD symptoms in children.
- ADHD symptoms in teenagers.
- What does ADHD look like?

## Understanding ADHD

- Can children have ADHD?
- Can adults have ADHD?
- Can teenagers have ADHD?
- Can girls have ADHD?
- Can boys have ADHD?
- Can toddlers have ADHD?
- Can ADHD be diagnosed in adults?
- Is ADHD hereditary?
- Is ADHD genetic?
- Is ADHD lifelong?
- How common is ADHD?
- Is ADHD a neurodevelopmental condition?

## Daily Life

- How does ADHD affect learning?
- How does ADHD affect school?
- How does ADHD affect work?
- How does ADHD affect relationships?
- Can ADHD affect sleep?
- Can ADHD affect concentration?
- Can ADHD affect behaviour?
- Can ADHD affect emotions?
- Can ADHD affect memory?
- Can ADHD affect organization?
- Can ADHD affect planning?
- Can ADHD affect time management?
- Can ADHD affect executive functioning?
- Can ADHD affect working memory?

## School & Learning

- Can ADHD affect grades?
- Can ADHD affect homework?
- Can ADHD make studying difficult?
- Can ADHD make learning difficult?
- Can ADHD affect classroom behaviour?
- Can ADHD affect academic performance?
- Why can't my child focus in school?
- My child with ADHD struggles in school.

## Behaviour

- Can ADHD cause hyperactivity?
- Can ADHD cause impulsive behaviour?
- Can ADHD cause inattention?
- Can ADHD affect listening?
- Can ADHD affect following instructions?
- Can ADHD make someone easily distracted?
- Can ADHD cause forgetfulness?

## Emotional Wellbeing

- Can ADHD affect emotions?
- Can ADHD cause emotional outbursts?
- Can ADHD cause frustration?
- Can ADHD affect self-esteem?
- Can ADHD cause mood swings?

## Treatment & Support

- Is ADHD treatable?
- Can ADHD be managed?
- Can ADHD improve?
- Can ADHD be cured?
- Can ADHD go away?
- Can ADHD improve with age?
- Can ADHD be treated without medication?
- Is medication necessary for ADHD?
- What medications are used for ADHD?
- Can ADHD medication help?
- What support is available for ADHD?
- Where can I learn more about ADHD?

## Personal Questions

- I think I have ADHD.
- I might have ADHD.
- I have ADHD.
- My child has ADHD.
- My child might have ADHD.
- My teenager has ADHD.
- My child can't focus.
- My child can't sit still.
- My child is always hyperactive.
- My child is always distracted.
- My child loses things all the time.
- My child forgets everything.
- I'm worried I have ADHD.
- I think my child has ADHD.

## Comparison Questions

- ADHD vs Autism
- ADHD vs Anxiety
- ADHD vs Depression
- ADHD vs Dyslexia
- ADHD vs OCD
- ADHD vs Bipolar Disorder
- Is it ADHD or autism?
- Is it ADHD or anxiety?
- Is it ADHD or dyslexia?
- What's the difference between ADHD and autism?
- What's the difference between ADHD and anxiety?

## Navigation Requests

- Show me ADHD.
- Open ADHD.
- ADHD page.
- ADHD article.
- ADHD guide.
- ADHD overview.
- ADHD resources.
- ADHD information.
- Read about ADHD.
- Learn more about ADHD.
- ADHD details.
- Open the ADHD page.

Aliases:

- ADHD
- ADD
- Attention Deficit Hyperactivity Disorder
- Attention Deficit Disorder
- ADD (older terminology)
- Inattentive ADHD
- Hyperactive ADHD
- Combined Type ADHD

Related Topics:

- Hyperactivity
- Impulsivity
- Executive Function
- Working Memory
- Organization
- Time Management
- Emotional Regulation
- Neurodevelopment
- Neuroplasticity

Do NOT Trigger:

General condition questions:

- What conditions do you cover?
- Tell me about conditions.
- Browse conditions.
- Show all conditions.
- Explore conditions.
- Which condition could this be?
- What condition might my child have?
- Help me understand possible conditions.
- Can you diagnose me?
- I think I have something.
- I'm not sure what condition this is.

Questions about other specific conditions:

- Autism
- Anxiety
- Depression
- Dyslexia
- Dyspraxia
- Dysgraphia
- Dyscalculia
- OCD
- Bipolar Disorder
- Tourette Syndrome
- Sensory Processing Disorder
- Speech Delay
- Developmental Delay

Fallback Rule:

If the Understanding Node cannot confidently identify **ADHD** as the specific condition,

DO NOT display this CTA.

Instead:

- If the user is asking about conditions in general → Display the Conditions Library CTA.
- Otherwise → Do not display any condition CTA.

Output Label:

Learn More About ADHD

CTA:

https://manascience.webflow.io/conditions/adhd
