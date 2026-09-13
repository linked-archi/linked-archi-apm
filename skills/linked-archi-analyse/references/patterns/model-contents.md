# What a model contains

Triggers: what is in this process, what does this model cover, which systems take part, who
is involved.

`core/inventory-summary` to see which models exist, `core/resolve-model` to turn a name into
the model IRI, then the notation template for that model's own vocabulary —
`notation/bpmn/process-components` groups a BPMN model's flow elements into where work
arrives, what runs automatically, what a person does, the participants, the data touched and
the outcomes. `notation/bpmn/process-flow` answers the adjacent question as edges; use that
one for order of steps, this one for who and what takes part. `notation/c4/containers` is the
equivalent for a C4 model. `core/define-term` explains any single element the reader stops on.

**Do not hand-write a folder path to get from a model to its elements.** How membership is
expressed is a profile fact (`navigation.model_membership`) and the templates carry the
`{{MEMBERSHIP:...}}` directive that resolves it. A hand-written traversal is right for one
dataset and silently empty for the next.

A modelled participant is a drawn intent. A `bpmn:ServiceTask` says the process is supposed
to call something; it is not evidence that a service exists, is deployed, or is reachable.

## Stop when

- the model is drawn at a level of detail that hides what was asked about. A coarse process
  hides the systems a detailed one would name, so an absent component is as likely a
  level-of-detail choice as a real absence;
- a participant has been listed. Saying what a model contains is finished; saying what runs
  needs evidence from outside these models.
