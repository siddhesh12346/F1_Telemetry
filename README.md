
# 🏎️ F1 Surface-Departure Warning

A machine learning–based **Formula 1 telemetry analysis and warning system** designed to investigate whether off-track / surface-departure events can be predicted using telemetry available before the event occurs.

The project focuses on **causal prediction**, temporal feature engineering, and event-level evaluation rather than simply classifying individual telemetry rows.

## 🎯 Project Objective

The primary objective is to develop and evaluate a machine learning system capable of providing an early warning of a potential **off-track / surface-departure event** approximately **1 second in advance**.

The system analyzes Formula 1 telemetry and derives historical features from information available at the current time step, while avoiding future information and data leakage.

## 🔬 Key Features

* Formula 1 telemetry preprocessing and analysis
* 1-second-ahead surface-departure prediction
* Causal time-series feature engineering
* Rolling telemetry statistics
* Lateral-G and dynamic vehicle behavior analysis
* Multiple machine learning experiments
* Threshold tuning using a validation circuit
* Held-out circuit evaluation
* Event-level recall measurement
* Warning lead-time analysis
* Session logging and driver analysis
* Real-time telemetry monitoring
* Caution-level warning detection

## 🧠 Machine Learning Approach

The project investigates different feature configurations and machine learning models to determine how much predictive information can be extracted from telemetry available before a surface-departure event.

### Prediction Target

A positive target is generated when a documented surface-departure condition occurs within the future prediction window.

The prediction is evaluated only when the vehicle is **not already in a departure state**, preventing the model from simply detecting an event that has already happened.

### Feature Engineering

The system uses historical and causal telemetry information such as:

* Speed
* Throttle
* Brake
* Steering
* Gear
* RPM
* Lateral acceleration
* Longitudinal acceleration
* Historical telemetry statistics
* Rolling means and standard deviations
* Dynamic changes in vehicle behavior
* Lap-distance information in selected experiments

Future telemetry and future control information are excluded from the predictive feature set.

## 🧪 Experimental Design

To reduce the risk of data leakage and overly optimistic results, the experiments use **circuit-based splits** rather than random row-level splitting.

### Dataset Split

| Purpose                       | Circuits      |
| ----------------------------- | ------------- |
| Training                      | Mexico, Monza |
| Validation / Threshold Tuning | Sakhir        |
| Final Held-Out Evaluation     | Spa           |

The threshold is selected using the validation circuit and then kept fixed for the final held-out evaluation.

## 📊 Model Experiments

The project evaluates multiple feature configurations and models, including:

* Logistic Regression
* Random Forest
* XGBoost

Different experiments investigate the effect of:

1. Basic telemetry features
2. Historical rolling features
3. Removal of lap-distance information
4. Different classification thresholds

Performance is evaluated using both frame-level and event-level metrics.

## 📈 Evaluation Metrics

The project uses several metrics because surface-departure events are relatively rare and class imbalance can make accuracy misleading.

### Frame-Level Metrics

* Precision
* Recall
* F1 Score
* ROC-AUC
* PR-AUC

### Event-Level Metrics

* Number of detected departure events
* Event recall
* Warning lead time
* Number of missed events

Event-level evaluation is particularly important because the goal is to provide a useful warning before an actual departure event rather than simply classifying individual telemetry frames.

## 🏁 Held-Out Spa Evaluation

The Spa dataset contains:

* **31,933 telemetry rows**
* **2,903 positive frames**
* **276 departure events**

The held-out circuit is not used for model training or threshold selection, providing a more realistic test of cross-circuit generalization.

## 💻 Application

The machine learning experiments form the analytical foundation of a larger telemetry application.

The application includes functionality for:

* Telemetry monitoring
* Surface-departure warning detection
* Session logging
* Driver analysis
* Warning event tracking
* Telemetry visualization

The goal is to connect offline machine learning experimentation with a practical telemetry-monitoring workflow.

## 🛠️ Tech Stack

**Programming Language**

* Python

**Machine Learning**

* Scikit-learn
* XGBoost

**Data Processing**

* Pandas
* NumPy

**Visualization**

* Plotly

**Application**

* Python-based telemetry processing and analysis

## 📂 Project Structure

```text
f1-surface-departure-warning/
│
├── ml_experiments/
│   └── refined_surface_warning.py
│
├── data/
│   └── ...
│
├── models/
│   └── ...
│
├── application/
│   └── ...
│
├── README.md
├── requirements.txt
└── .gitignore
```

> The exact structure may change as the application develops.

## 🚀 Installation

Clone the repository:

```bash
git clone https://github.com/YOUR_USERNAME/f1-surface-departure-warning.git
```

Navigate into the project:

```bash
cd f1-surface-departure-warning
```

Create a virtual environment:

```bash
python -m venv venv
```

Activate it on Windows:

```bash
venv\Scripts\activate
```

Install dependencies:

```bash
pip install -r requirements.txt
```

## ▶️ Running the ML Experiment

Run the refined surface-departure experiment:

```bash
python ml_experiments/refined_surface_warning.py
```

Additional application components can be launched according to their respective modules.

## ⚠️ Important Considerations

This project is a **research and feasibility study**, not a production-grade driver safety system.

The model's performance can vary depending on:

* Circuit characteristics
* Driver behavior
* Telemetry quality
* Event definition
* Class imbalance
* Feature availability
* Generalization to unseen circuits

The project therefore emphasizes transparent evaluation and leakage prevention rather than presenting the model as a definitive predictor.

## 🔭 Future Work

Potential extensions include:

* Larger multi-season telemetry datasets
* Additional circuits and drivers
* Sequence-based deep learning models
* LSTM / GRU architectures
* Transformer-based telemetry models
* Driver-specific modeling
* More advanced anomaly detection
* Improved real-time inference
* Live telemetry integration
* Interactive driver comparison
* More detailed event classification
* Automated model retraining

## 📚 Research Focus

This project explores the intersection of:

**Formula 1 Telemetry × Time-Series Machine Learning × Predictive Warning Systems**

The main research question is whether vehicle telemetry patterns preceding an off-track / surface-departure event contain enough information to generate a useful early warning while maintaining strict causal constraints.

## 👤 Author

**Siddhesh Kulkarni**

B.Tech Computer Science & Engineering
MIT World Peace University

GitHub: [github.com/siddhesh12346](https://github.com/siddhesh12346)

LinkedIn: [linkedin.com/in/siddhesh-kulkarni-97b562236](https://www.linkedin.com/in/siddhesh-kulkarni-97b562236)

---

⭐ If you find this project interesting, feel free to explore the experiments and methodology.
