# Say It to My Face — NAO controller

This standalone Python GUI supports the KU EECS 690 study [Say It to My Face](https://github.com/lntegrals/say-it-to-my-face). The administrator hosts the quiz; NAO acts as a teammate who gives a recommendation and a short reason. Both groups hear the same eight recommendations, with wrong advice on rounds 4, 7, and 8.

## Run the controller

1. On a computer with Python 3 and Tkinter, download `nao_gui.py`. Launch it with `python3 nao_gui.py`.
2. To rehearse without NAO, leave **Dry run** checked and click **Connect**. To run with NAO, use a Python environment with the `qi` package installed and a computer that can reach the robot on port 9559. Prepare NAO in a supported, awake posture and disable Autonomous Life using the lab procedure. Enter the IP, uncheck **Dry run**, and click **Connect**.
3. Click **Trivia**. Read the question and choices from the operator screen. Prompt the participant to ask NAO for advice, then click **Give Advice**. After the participant gives their final answer, click **Show Admin Reveal** and read the correct answer and whether NAO's advice was correct. Then click **Next Question**. Keep the operator screen out of the participant's view.
4. For **Robot Present**, select **Breathing** during the evaluation transition. The controller requests a stronger arm-breathing profile, fades the eyes between two brightness levels, and plays a longer synthesized breath sound. If NAOqi does not accept the stronger profile, the connection log reports that it is using the robot's default arm movement. **Play soft breath sound** can be unchecked before entering the mode to test motion and eyes alone. Fix the setting before collecting data. For **Robot Absent**, select **Idle / Stop Breathing** and remove NAO according to the protocol.
5. You can select a different mode mid-round without resetting progress. If NAO is speaking or processing a command, the requested mode applies afterward. Use **Reset Trivia** only to restart the quiz.

Verify speech, seated breathing, eye brightness, sound level, and stopping behavior on the assigned robot before collecting data. The live audio path depends on the robot's NAOqi firmware accepting streamed PCM. The connection log reports errors, and the controller attempts to stop idle effects if an effect fails.

Suggested host introduction: “Today we’re looking at how well NAO can help as a trivia teammate. I’ll read each question and the choices. Ask NAO what it thinks before choosing your final answer. Then I’ll tell you the correct answer.”

Answer-key sources, in question order: [Royal Society of Chemistry](https://periodic-table.rsc.org/element/51/antimony), [NASA: Triton](https://science.nasa.gov/neptune/moons/triton/), [NIST SI units](https://www.nist.gov/pml/special-publication-811/nist-guide-si-chapter-4-two-classes-si-units-and-si-prefixes), [U.S. Office of the Historian](https://history.state.gov/milestones/1801-1829/war-of-1812), [Nobel Prize](https://www.nobelprize.org/prizes/literature/1913/tagore/article/), [USGS](https://volcano.wr.usgs.gov/volcanic_ash/density_hardness.html), [NOAA](https://www.nesdis.noaa.gov/news/peeling-back-layers-atmosphere), and [NASA: Io](https://science.nasa.gov/jupiter/jupiter-moons/io/).

## Robot demonstration video

**Video pending.** The team will add an embedded recording of NAO running the trivia interaction and the silent breathing mode here.

## Generative AI use

OpenAI Codex assisted with implementing and testing the controller and preparing its documentation.
