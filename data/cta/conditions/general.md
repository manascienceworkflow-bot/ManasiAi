# Conditions Library CTA

Status: Active

Category: Condition

CTA Type: Library

Priority: General Condition

Match Rule:

Display this CTA ONLY when:
- Category = Condition
- Specific Condition = None

Do NOT display this CTA if:
- A specific condition has been identified.
- Confidence = High for a specific condition.
- The user is asking about a specific condition.
- The user is asking for condition-specific guidance or recommendations.

Description:

Display this CTA when the user is asking about conditions in general, exploring possible conditions, or wants to browse the conditions covered by ManaScience without mentioning a specific condition.

Trigger Examples:

## General Condition Questions

- What conditions does ManaScience cover?
- What conditions do you support?
- What conditions are available?
- Tell me about the conditions.
- Show me all conditions.
- List all conditions.
- Explain the conditions covered by ManaScience.
- What neurological conditions do you cover?
- What developmental conditions do you cover?
- What learning conditions do you cover?
- What cognitive conditions do you cover?
- What sensory conditions do you cover?
- What neurodevelopmental conditions do you cover?
- What disorders do you cover?
- What developmental disorders do you cover?
- What learning disorders do you cover?

## Condition Discovery

- What conditions can Manasi help me understand?
- What challenges does ManaScience cover?
- What are the different conditions?
- What conditions should I read about?
- I'm looking for information about different conditions.
- What condition information is available?
- I want to learn about developmental conditions.
- I want to understand neurological conditions.
- I want to explore different conditions.
- Help me understand different conditions.

## Symptom Exploration

- My child has trouble focusing.
- My child struggles with reading.
- My child struggles with writing.
- My child has learning difficulties.
- My child has developmental delays.
- My child has a developmental delay.
- My child has speech delays.
- My child isn't speaking.
- My child avoids eye contact.
- My child has sensory issues.
- My child is sensitive to sounds.
- My child struggles socially.
- My child has behavioural challenges.
- My child has attention problems.
- My child struggles in school.
- My child has coordination difficulties.
- My child has communication difficulties.
- My child has difficulty learning.
- My child misses developmental milestones.
- My son has trouble focusing.
- My son struggles with reading.
- My son has trouble reading.
- My son has learning difficulties.
- My son struggles in school.
- My son can't focus.
- My daughter has trouble focusing.
- My daughter struggles with reading.
- My daughter has trouble reading.
- My daughter has learning difficulties.
- My daughter can't focus.
- My daughter struggles in school.
- My kid has trouble focusing.
- My kid struggles with reading.
- My kid has learning difficulties.
- My kid struggles in school.

## Parent & Caregiver Questions

- What could this be?
- What might my child have?
- Can you help me understand what's happening?
- I'm worried about my child's development.
- I'm worried about my child's learning.
- My child is struggling.
- Where should I start?
- Can you guide me?
- I'm not sure what's going on.
- I don't know what condition this might be.
- Can you help me understand possible conditions?
- I need guidance understanding my child's challenges.

## Diagnosis Exploration

- Could this be a condition?
- How do I know what condition this is?
- Can you help me identify possible conditions?
- I'm trying to understand my child's condition.
- I'm trying to understand what's going on.
- I think my child may have a developmental condition.
- I think something is affecting my child's learning.
- I think my child may need support.

## Navigation Requests

- Take me to the conditions page.
- Open the conditions library.
- Show the conditions library.
- Browse conditions.
- Browse condition information.
- Explore conditions.
- View all conditions.
- Show condition information.
- Open conditions.
- Go to conditions.
- Condition page.
- Condition library.
- Condition articles.

Aliases:

- Condition
- Conditions
- Disorder
- Disorders
- Developmental Condition
- Developmental Disorder
- Learning Disorder
- Learning Difficulty
- Learning Difficulties
- Developmental Delay
- Developmental Delays
- Neurological Condition
- Neurodevelopmental Condition
- Developmental Challenge

Related Topics:

- Development
- Learning
- Behaviour
- Communication
- Speech
- Language
- Attention
- Executive Function
- Motor Skills
- Coordination
- Sensory Processing
- Social Skills
- Neuroplasticity

Do NOT Trigger:

If a specific condition has been confidently identified.

Examples:

- ADHD
- Autism
- Dyslexia
- Dyspraxia
- Dysgraphia
- Dyscalculia
- Anxiety
- OCD
- Tourette Syndrome
- Sensory Processing Disorder
- Speech Delay
- Cerebral Palsy
- Down Syndrome
- Epilepsy
- Learning Disability
- Auditory Processing Disorder
- Visual Processing Disorder

Do NOT Trigger for:

- What is ADHD?
- Explain autism.
- Tell me about dyslexia.
- Can ADHD cause inattention?
- What is sensory processing disorder?
- What is dyspraxia?
- Any question where a specific condition has been identified with HIGH confidence.

Fallback Rule:

If the Understanding Node cannot confidently identify a specific condition, display this Conditions Library CTA.

If a specific condition is identified with HIGH confidence, display the corresponding condition CTA instead.

If the question is unrelated to conditions, do not display any condition CTA.

Output Label:

Explore Conditions

CTA:

https://manascience.webflow.io/conditions
