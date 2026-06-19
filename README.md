# Night Train Target Network

An open-source initiative by [Back-on-Track](https://back-on-track.eu) to design and evaluate a European night train target network that could realistically be implemented by 2032.

## Vision

Back-on-Track wants to put a serious, evidence-based night train network proposal in front of the new European Commission and other key political stakeholders. The study needs to answer three core questions:

- **Which routes should be part of the network - in addition to the ones that exist today?** — based on future demand potential, including passengers likely to shift from air travel.
- **How much public subsidy is needed** — per route and for the network as a whole — to create the framework conditions under which operators can run economically sustainable services?
- **Which night train concepts work best** on which routes or parts of the network?

To build broad acceptance for the results from the start, we're drawing on Back-on-Track's community of members, lobbyists, experts and politicians to crowdsource route and train concept ideas, evaluate them transparently, and use the strongest proposals as the foundation for the target network.

## How we get to the study results

1. **Prepare the model [Current phase]** — collect the data and cost/revenue model used to evaluate the economic feasibility of individual routes and the full network.
2. **Crowdsource ideas** — a web-based tool lets community members design routes (timetables, geography, X/Y-shaped route bundles), pick a train composition or propose a custom one, and see cost, revenue and demand-shift results instantly — gamified against other members' submissions.
3. **Select the best proposals** — the most economically sound suggestions form the basis of the target network, with further adjustments, additions or optimization.
4. **Evaluate the network** — answer the three core questions above and publish the results (study paper, interactive map, etc.).
5. **Close the loop** — share results back with the community and the wider public, crediting contributions.

Each submitted route is scored on:

- Potential shift from air travel (flights, seats, seat-km)
- CO₂ reductions (t CO₂e)
- Subsidy needed per shifted seat-km (€/seat-km)
- Subsidy needed per tonne of CO₂ reduced (€/t CO₂e)

## This repository

This repo hosts the technical side of the project — backend and frontend. Data for is stored in a postgres database on our server of back-on-track.

## Contributing

Contributions of any kind — code, data, route ideas, documentation — are very welcome!

For coordination reasons, please **send a short email before you start working on something**, so we can avoid duplicate effort and keep contributions aligned with the overall direction:

👨 **Current project lead: David Wedekind**

📧 **targetnetwork-wg@back-on-track.eu**


We'll be introducing a formal request-control process for pull requests shortly. In the meantime — and after — the basic workflow is:

1. Always pull freshly from `master` before starting any work.
2. Do your work on your own branch.
3. Open a pull request when ready — it will go through request-control review by the project lead.
4. Keep branch lifetimes short: merge within **days, not months**.

---

Questions before diving in? Reach out to the email above.