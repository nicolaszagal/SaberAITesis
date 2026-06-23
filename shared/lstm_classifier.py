"""
lstm_classifier.py — copia literal de dataset/lstm_4class/models/lstm_classifier.py.

Modelo BiLSTM para clasificación de acciones de esgrima sable: 192
features, 4 clases (AttackA, AttackB, ResponseA, ResponseB), luz Favero
como input real del modelo (concatenada al pooled output antes del FC) y
attention pooling. Es el modelo del checkpoint
`dataset/lstm_4class/checkpoints/best_model.pt` desplegado en Cloud.

Reemplaza la versión anterior (182 features, 6 clases, sin luz, mean
pooling) — ese pipeline quedó descartado (ver PLAN_ARQUITECTURA_DDD.md).
"""

import torch
import torch.nn as nn


class LSTMClassifier(nn.Module):
    def __init__(
        self,
        input_size: int   = 192,
        hidden_size: int  = 64,
        num_layers: int   = 1,
        num_classes: int  = 4,
        dropout: float    = 0.5,
        luz_size: int     = 0,
        use_attention: bool = True,
    ):
        """
        Args:
            input_size:     Dimensión del vector de features por frame (192).
            hidden_size:    Unidades ocultas por dirección del BiLSTM.
            num_layers:     Capas LSTM (1 = sin dropout interno).
            num_classes:    Clases de salida (4).
            dropout:        Dropout sobre el pooled output antes de FC.
            luz_size:       Features de luz Favero a concatenar tras pooling.
                            0 = desactivado, 2 = [has_luz_A, has_luz_B].
            use_attention:  True = additive attention pooling (recomendado).
                            False = mean pooling.
        """
        super().__init__()

        self.use_attention = use_attention
        self.luz_size      = luz_size

        self.lstm = nn.LSTM(
            input_size=input_size,
            hidden_size=hidden_size,
            num_layers=num_layers,
            batch_first=True,
            bidirectional=True,
            dropout=dropout if num_layers > 1 else 0.0,
        )

        if use_attention:
            # Additive attention: dos capas lineales para puntuar cada frame
            self.attn_fc = nn.Linear(hidden_size * 2, hidden_size)  # proyección
            self.attn_v  = nn.Linear(hidden_size, 1, bias=False)    # scoring

        self.dropout = nn.Dropout(dropout)
        # FC: (hidden*2 + luz_size) → num_classes
        self.fc = nn.Linear(hidden_size * 2 + luz_size, num_classes)

    def forward(
        self,
        x: torch.Tensor,
        lengths: torch.Tensor,
        luz: torch.Tensor = None,
        return_attention: bool = False,
    ) -> torch.Tensor:
        """
        Args:
            x:                (B, T, input_size) — secuencias paddeadas
            lengths:          (B,) — longitud real de cada secuencia
            luz:              (B, luz_size) — features de luz Favero, o None
            return_attention: Si True, devuelve (logits, weights) en vez de logits.
                              Solo disponible con use_attention=True.

        Returns:
            logits: (B, num_classes)
            weights: (B, T) — pesos de atención por frame [solo si return_attention]
        """
        packed = nn.utils.rnn.pack_padded_sequence(
            x, lengths.cpu(), batch_first=True, enforce_sorted=False
        )
        output, _ = self.lstm(packed)
        output, _ = nn.utils.rnn.pad_packed_sequence(output, batch_first=True)
        # output: (B, T_max, hidden*2)

        mask = (
            torch.arange(output.size(1), device=x.device).unsqueeze(0)
            < lengths.unsqueeze(1).to(x.device)
        )  # (B, T_max)

        if self.use_attention:
            scores = self.attn_v(
                torch.tanh(self.attn_fc(output))
            ).squeeze(-1)                          # (B, T_max)

            scores = scores.masked_fill(~mask, float('-inf'))
            weights = torch.softmax(scores, dim=1)  # (B, T_max)

            pooled = (output * weights.unsqueeze(-1)).sum(dim=1)  # (B, hidden*2)
        else:
            output = output * mask.unsqueeze(-1).float()
            pooled = output.sum(dim=1) / lengths.to(x.device).unsqueeze(1).float()
            weights = None

        pooled = self.dropout(pooled)

        if self.luz_size > 0 and luz is not None:
            pooled = torch.cat([pooled, luz.float()], dim=1)  # (B, hidden*2 + luz_size)

        logits = self.fc(pooled)  # (B, num_classes)

        if return_attention and self.use_attention:
            return logits, weights
        return logits


CLASSES = ["AttackA", "AttackB", "ResponseA", "ResponseB"]
