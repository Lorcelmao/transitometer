# CO5173 Data Engineering — Instructor PROJECT Requirements (authoritative extract)

Source (authoritative): `DE_Presentation and Project Descriptions and Requirements-Semester 1-2026-2027.pdf`
Course: Data Engineering (CO5173), Sem 1 2026-2027, Assoc. Prof. Dr. Võ Thị Ngọc Châu (HCMUT).
Extraction method: `pdftotext -layout`. Verbatim quotes shown in `"..."`.

Scope note: This extract covers **PROJECT only**. The Presentation assignment criteria (video 10 min,
in-class presentation, presentation-only rubric) are intentionally excluded per task instructions.
Overlapping general criteria that legitimately apply to the Project are retained.

---

## 1. Objectives (course-level, applies to Project)
- `"Presentation and Project aim at ... self-study and work in group on data engineering-related topics. They also enable the learners to develop an application that can reflect the effectiveness of data engineering results..."`

## 2. Application domain (our assigned domain)
- `"The learners are asked to work on one application domain assigned for each group which is unique in the scope of our course."`
- Our assigned domain: **Transportation**.
- With the domain: `"identify the potential key user groups that the learners would like to support."`
- Then: `"determine the business requirements that need data prepared by data engineering. Such business requirements are related to data analysis, data science, data mining, business intelligence systems, decision support systems, and so on."`

## 3. Topic
- `"Build a system where your data engineering solution is proved successful (in a specific application domain)."`
- `"The topic requires the learners to do data engineering in such a way that the resulting data can be utilized specifically for users in an application domain."`
- Three main product parts:
  1. `"(i). Business and related data in an application domain"`
  2. `"(ii). Data engineering for the business requirements"`
  3. `"(iii). Application development to bring the results to the real world"`
- `"In the scope of the course, data management and processing aspects are focused. Therefore, each group needs to clarify and work with several technologies selected for data management and processing."`

### 3.1 Indicative technology menu (from instructor — not exhaustive)
- **Data management:** Redshift, Hive, Synapse Analytics, Cassandra, BigQuery (BigLake), CouchBase, Databricks, Neo4J, RavenDB, Dynamo, Oracle data lakehouse, ...
- **Data processing:** Flink, Spark Streaming, Hadoop Map-Reduce, Storm, Kafka Stream, ...

### 3.2 Business requirement minimum
- `"For each group, at least 2*n business requirements must be defined to utilize the data from data engineering where n is the number of members."`
- **n = 4 members → minimum 8 business requirements.**
- `"The business requirements need to show the support for the business objectives of the enterprise in the application domain uniquely selected by each group."`
- `"Each group also needs to provide the rationales behind the data engineering's support for those requirements"`
- `"and evaluate the selected technologies in the solution for the system."`
- `"Alternative solutions might be considered for benchmarking the selected technologies from the different perspectives, especially in the Big Data context."`

## 4. Project-specific deliverables (verbatim list, section 2.2.ii)
1. `"Introduce the context of the project topic"`
2. `"Introduce stakeholders (especially users), along with business requirements and data usage needs, in order to shape a data-driven application for the application domain of each group"`
3. `"Present the expected data sources and data characteristics that should be considered when implementing data engineering"`
4. `"Present the data engineering solution and introduce at least one alternative solution (for comparison)"`  ← **alternative solution REQUIRED**
5. `"Present the technology for data management, the technology for data processing, and approaches to leveraging these technologies for the application"`
6. `"Develop the application for the project topic"`
7. `"Evaluate the data engineering solution and data-driven application based on the following criteria:"`
   - `"Data correctness after data engineering is performed"`
   - `"Performance of the data engineering solution"`
   - `"Effectiveness of supporting data exploitation through the application"`
8. `"Conclusions about the project"`

## 5. Submission formats & weights (PROJECT part)
- `"A final technical report in a pdf file (10% of the total score; but a required one for scoring the Project part)."`
- `"Presentation: a presentation file. A presentation file is a pdf file (5% ... required)"` — must show `"the data engineering solution ... and the application that demonstrates the effectiveness of this solution"`.
- `"A video in mp4 or webm format (5% ... required) is completed along with a presentation and application demonstration in 20-30 minutes."`
- `"Product: A proof of the application development (15% ... required) ... showing a demonstration of the resulting application that can be executed and evaluated."`
- `"All submitted files for assessment need to be named with your group ID."`
- Due: `"the end of our course."`

## 6. Evaluation criteria (PROJECT)
| Criterion | Weight | Top-band (8.5–10) requirement |
|---|---|---|
| Report Structure | 1/10 | well organized, all sections clear & logical |
| Technology Content | 4/10 | technology presented thoroughly for the group's application, **>3 illustrative examples** |
| Application Content | 4/10 | **<10% of required project content missing** |
| Evaluation of Technology Used in the Project | 1/10 | systematic evaluation; **>85% of evaluation criteria clearly defined** |
| Video content | 5/10 | consistent with **85–100% of slides** |
| Video presentation | 4/10 | confident, coherent, well-coordinated, appropriate interaction |
| Video duration | 1/10 | nearly meets required duration (20–30 min) |
| Slide structure | 2/10 | all sections appropriately detailed (avoid >7 sections; avoid <4) |
| Slide content | 6/10 | rich, well-reasoned, detailed discussion + appropriate illustrative examples |
| Slide presentation format | 2/10 | nearly no errors |
| User Interface Design | 2/10 | interface fits application context, considers user characteristics, harmonious presentation + interaction |
| Application Implementation | 8/10 | `"For each successful demonstration of a business requirement and corresponding data exploitation result, the score is calculated as 4/n/10, where n is the number of group members."` (n=4) |

## 7. Bonus (section 4)
- `"Groups: More alternative solutions with excellent evaluation results, more interesting business requirements with more user groups, more discussions with research results for the projects."`

---

## 8. Derived PROJECT checklist (must-satisfy for planning)
- [ ] C1 Unique Transportation domain framing (not generic).
- [ ] C2 Named key user group(s) / stakeholders in Transportation.
- [ ] C3 >= 8 business requirements, each tied to a business objective and each demonstrable.
- [ ] C4 For each BR: rationale of how data engineering enables it.
- [ ] C5 Explicit data sources + data characteristics.
- [ ] C6 A data engineering solution: >=1 data-management technology AND >=1 data-processing technology (from/consistent with the instructor's menu), with justification.
- [ ] C7 **At least one alternative solution** for comparison/benchmarking, esp. Big Data context.
- [ ] C8 An executable application that exposes data-engineering results to users.
- [ ] C9 Evaluation: (a) data correctness, (b) performance, (c) application data-exploitation effectiveness — systematic and clearly-defined criteria (>85%).
- [ ] C10 >3 illustrative technology examples.
- [ ] C11 Full lifecycle demonstration (ingest → manage → process → serve → exploit) reproducible for evaluation.
- [ ] C12 Report + slide deck + 20–30 min video + runnable product, named by group ID.

## 9. Notes / open items
- Group ID and member names: not yet recorded (needed at submission time only).
- Ambiguity noted: `"4/n/10"` per demonstrated BR — read as: each successfully demonstrated BR + data-exploitation result contributes toward the 8/10 Application Implementation score; more demonstrated BRs ⇒ more score. Directionally: maximize number and demonstrability of BRs (bounded by realism), and note that the bonus explicitly rewards more BRs / more user groups.
- Ambiguity noted: "at least 2*n" is a floor of 8; the bonus rewards more. Planning should deliver a core of 8–10 with a clear path to more.
