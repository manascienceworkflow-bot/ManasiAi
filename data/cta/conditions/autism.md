# Autism CTA

Status: Active

Category: Condition

CTA Type: Individual Condition

Priority: Specific Condition

Match Rule:

Display this CTA ONLY when:
- Category = Condition
- Specific Condition = Autism
- Confidence = High

Do NOT display this CTA if:
- Specific Condition = None
- Confidence is Low or Medium.
- The user is asking about conditions in general.
- The user is asking which condition they may have.
- The user is asking for a diagnosis.
- Another specific condition has been identified.

Description:

Display this CTA only when the conversation is specifically about Autism (Autism Spectrum Disorder / Autism Spectrum Condition).

Trigger Examples:

## Learning About Autism

- What is autism?
- Explain autism.
- Tell me about autism.
- What is ASD?
- Explain ASD.
- Tell me about ASD.
- What is Autism Spectrum Disorder?
- Explain Autism Spectrum Disorder.
- What is Autism Spectrum Condition?
- What causes autism?
- Why does autism happen?
- What are the different types of autism?
- Is autism a spectrum?
- What does the autism spectrum mean?

## Symptoms & Signs

- What are the symptoms of autism?
- What are the signs of autism?
- What are the early signs of autism?
- How do I know if my child has autism?
- How is autism diagnosed?
- How do doctors diagnose autism?
- Can autism be diagnosed?
- Autism symptoms in toddlers.
- Autism symptoms in children.
- Autism symptoms in teenagers.
- Autism symptoms in adults.
- What does autism look like?
- What are autism red flags?

## Understanding Autism

- Can children have autism?
- Can adults have autism?
- Can teenagers have autism?
- Can girls have autism?
- Can boys have autism?
- Can toddlers have autism?
- Is autism genetic?
- Is autism hereditary?
- Is autism lifelong?
- How common is autism?
- Is autism a neurodevelopmental condition?
- Is autism a disability?
- What is high-functioning autism?
- What is low-functioning autism?
- What is Asperger syndrome?
- How is Asperger syndrome related to autism?

## Social Communication

- Why does my child avoid eye contact?
- Why doesn't my child make eye contact?
- Why doesn't my child respond to their name?
- Why doesn't my child play with other children?
- Why does my child struggle socially?
- Why does my child have trouble communicating?
- Why does my child not speak?
- Why is my child's speech delayed?
- Why does my child repeat words or phrases?
- What is echolalia?

## Behaviour & Sensory

- Why does my child have repetitive behaviours?
- Why does my child flap their hands?
- Why does my child spin?
- Why does my child line things up?
- Why does my child have meltdowns?
- Why does my child have sensory sensitivities?
- Why is my child sensitive to sounds?
- Why is my child sensitive to touch?
- Why does my child have a restricted diet?
- What are special interests in autism?
- What is stimming?
- Why does my child stim?

## Daily Life

- How does autism affect learning?
- How does autism affect school?
- How does autism affect friendships?
- How does autism affect communication?
- Can autism affect behaviour?
- Can autism affect emotions?
- Can autism affect sleep?
- Can autism affect eating?
- Can autism affect sensory processing?
- How does autism affect daily life?

## Treatment & Support

- Is autism treatable?
- Can autism be treated?
- Can autism improve?
- Can autism be cured?
- Can autism symptoms improve?
- Can early intervention help autism?
- What therapies help autism?
- What support is available for autism?
- Where can I learn more about autism?
- How can I support my autistic child?

## Personal Questions

- I think my child has autism.
- My child might have autism.
- My child has autism.
- My child was diagnosed with autism.
- My child was diagnosed with ASD.
- I'm worried my child has autism.
- I'm autistic.
- I have autism.
- I might be autistic.
- My son avoids eye contact.
- My daughter avoids eye contact.
- My son doesn't respond to his name.
- My daughter doesn't respond to her name.
- My child isn't talking yet.
- My child prefers to be alone.

## Comparison Questions

- Autism vs ADHD
- Autism vs Asperger syndrome
- Autism vs Sensory Processing Disorder
- Autism vs Speech Delay
- Is it autism or ADHD?
- Is it autism or a speech delay?
- What's the difference between autism and ADHD?
- What's the difference between autism and Asperger syndrome?

## Navigation Requests

- Show me autism.
- Open autism.
- Autism page.
- Autism article.
- Autism guide.
- Autism overview.
- Autism resources.
- Autism information.
- Read about autism.
- Learn more about autism.
- Autism details.
- Open the autism page.
- ASD page.
- ASD article.
- ASD information.

Aliases:

- Autism
- Autism Spectrum Disorder
- Autism Spectrum Condition
- Autistic
- Asperger Syndrome
- Aspergers
- High-Functioning Autism

Related Topics:

- Social Communication
- Social Skills
- Eye Contact
- Speech Delay
- Language Development
- Sensory Sensitivity
- Sensory Processing
- Repetitive Behaviour
- Special Interests
- Echolalia
- Stimming
- Executive Function
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

- ADHD
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

If the Understanding Node cannot confidently identify **Autism** as the specific condition,

DO NOT display this CTA.

Instead:

- If the user is asking about conditions in general → Display the Conditions Library CTA.
- Otherwise → Do not display any condition CTA.

Output Label:

Learn More About Autism

CTA:

https://manascience.webflow.io/conditions/autism
