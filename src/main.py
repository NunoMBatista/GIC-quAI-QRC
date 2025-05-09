import os
import sys
import numpy as np
import random
import torch
import matplotlib.pyplot as plt
from typing import Dict, Any, Tuple, Optional

# Fix the import path for the qrc_polyp_python module
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

# Import custom modules
from autoencoder import Autoencoder, GuidedAutoencoder

from data_processing import load_dataset, show_sample_image, flatten_images, one_hot_encode
from feature_reduction import (
    apply_pca, apply_pca_to_test_data, 
    apply_autoencoder, apply_autoencoder_to_test_data,
    apply_guided_autoencoder, apply_guided_autoencoder_to_test_data,
    scale_to_detuning_range
)
from qrc_layer import DetuningLayer
from training import train
from visualization import plot_training_results, print_results

# Update import to use the new function
from cli_utils import get_args
import argparse

def main(args: Optional[argparse.Namespace] = None) -> Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, torch.nn.Module]]:
    """
    Main function to run the quantum reservoir computing pipeline.
    
    Parameters
    ----------
    Optional[argparse.Namespace]
    Command line arguments
    
    Returns
    -------
    Dict[str, Tuple[np.ndarray, np.ndarray, np.ndarray, torch.nn.Module]]
        Dictionary of results for each model
    """
    
    # Parse arguments if not provided
    if args is None:
        args = get_args()
    
    # Set random seed for reproducibility
    random.seed(args.seed)
    np.random.seed(args.seed)
    torch.manual_seed(args.seed)
    

    print("""
          
          =========================================
                    LOADING THE DATASET
          =========================================
          
          """)
    

    DATA_DIR = args.data_dir if args.data_dir else os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", "datasets")

    # Load dataset based on the specified dataset type
    if args.dataset_type == 'mnist':
        # Define the path to MNIST dataset
        data_train, data_test = load_dataset(
            'mnist',
            data_dir=DATA_DIR,
            target_size=tuple(args.target_size)
        )
        
    else:            
        DATASET_DIR = os.path.join(DATA_DIR, args.dataset_type)
        if not os.path.exists(DATASET_DIR):
            raise ValueError(f"Dataset directory does not exist: {DATASET_DIR}")
        
        data_train, data_test = load_dataset(
            'image_folder',
            data_dir=DATASET_DIR,
            target_size=tuple(args.target_size),
            split_ratio=args.split_ratio
        )

    print(f"Dataset loaded: {args.dataset_type}")
    print(f"Number of training samples: {data_train['metadata']['n_samples']}")
    print(f"Number of test samples: {data_test['metadata']['n_samples']}")
    print(f"Number of classes: {data_train['metadata']['n_classes']}")
    
    
    print("""
          
          =========================================
                PERFORMING FEATURE REDUCTION
          =========================================
          
          """)
    
    # Determine reduction dimension
    dim_reduction = args.dim_reduction
    
    # Perform feature reduction based on selected method
    method_name = args.reduction_method.lower()
    reduction_name = method_name.upper()  # For display in result labels
    
    if method_name == "pca":
        # Apply PCA reduction
        print("Using PCA for feature reduction...")
        xs_raw, reduction_model, spectral = apply_pca(
            data=data_train, 
            dim_pca=dim_reduction, 
            num_examples=args.num_examples
        )
        
        # Apply PCA to test data
        print("Applying PCA to test data...")
        test_features_raw = apply_pca_to_test_data(
            data=data_test,
            pca_model=reduction_model,
            dim_pca=dim_reduction,
            num_examples=args.num_test_examples
        )
        
    elif method_name == "autoencoder":
        # Use GPU if available and requested
        device = 'cuda' if args.gpu and torch.cuda.is_available() else 'cpu'
        if args.gpu and not torch.cuda.is_available():
            print("Warning: GPU requested but not available. Using CPU instead.")
        
        print(f"Using autoencoder for feature reduction (device: {device})...")
        
        # Apply autoencoder reduction with improved parameters
        xs_raw, reduction_model, spectral = apply_autoencoder(
            data=data_train,
            encoding_dim=dim_reduction,
            num_examples=args.num_examples,
            hidden_dims=args.autoencoder_hidden_dims,
            batch_size=args.autoencoder_batch_size,
            epochs=args.autoencoder_epochs,
            learning_rate=args.autoencoder_learning_rate,
            device=device,
            verbose=not args.no_progress,
            use_batch_norm=True,
            dropout=0.1,
            weight_decay=1e-5
        )
        
        # Log the spectral range to help diagnose scaling issues
        print(f"Encoded data spectral range: {spectral}")
        
        # Apply autoencoder to test data
        print("Applying autoencoder to test data...")
        test_features_raw = apply_autoencoder_to_test_data(
            data_test,
            reduction_model,
            args.num_test_examples,
            device=device,
            verbose=not args.no_progress
        )
    
    elif method_name == "guided_autoencoder":
        # Use GPU if available and requested
        device = 'cuda' if args.gpu and torch.cuda.is_available() else 'cpu'
        if args.gpu and not torch.cuda.is_available():
            print("Warning: GPU requested but not available. Using CPU instead.")
        
        print(f"Using quantum guided autoencoder for feature reduction (device: {device})...")
        
        # First create quantum layer for guided training
        print("Creating quantum layer for guided autoencoder training...")
        quantum_layer = DetuningLayer(
            geometry=args.geometry,
            n_atoms=dim_reduction,
            lattice_spacing=args.lattice_spacing,
            rabi_freq=args.rabi_freq,
            t_end=args.evolution_time,
            n_steps=args.time_steps,
            readout_type=args.readout_type,
            encoding_scale=args.encoding_scale,
            print_params=False  # No need to print params twice
        )
        
        # Apply guided autoencoder reduction with improved parameters
        xs_raw, reduction_model, spectral = apply_guided_autoencoder(
            data_train,
            quantum_layer=quantum_layer,
            encoding_dim=dim_reduction,
            num_examples=args.num_examples,
            hidden_dims=args.autoencoder_hidden_dims,
            alpha=args.guided_alpha,
            beta=args.guided_beta,
            batch_size=args.guided_batch_size,
            epochs=args.autoencoder_epochs,
            learning_rate=args.autoencoder_learning_rate,
            quantum_update_frequency=args.quantum_update_frequency,
            n_shots=args.n_shots,
            device=device,
            verbose=not args.no_progress,
            use_batch_norm=True,  # Enable batch normalization
            dropout=0.1,  # Add dropout for regularization
            weight_decay=1e-5  # Add weight decay
        )
        
        # Log the spectral range to help diagnose scaling issues
        print(f"Encoded data spectral range: {spectral}")
        
        # Apply guided autoencoder to test data
        print("Applying guided autoencoder to test data...")
        test_features_raw = apply_guided_autoencoder_to_test_data(
            data_test,
            reduction_model,
            args.num_test_examples,
            device=device,
            verbose=not args.no_progress
        )
        
    else:
        raise ValueError(f"Unknown reduction method: {method_name}")
    
    # Get targets for training and testing (limited to the examples we're using)
    train_targets = data_train["targets"][:args.num_examples]
    test_targets = data_test["targets"][:args.num_test_examples]

    print("""
    
        =========================================
                  ONE-HOT ENCODING TARGETS
        =========================================
    
        """)


    # Perform one-hot encoding
    n_classes = data_train["metadata"]["n_classes"]
    ys_encoded, encoder = one_hot_encode(train_targets, n_classes)
    ys = ys_encoded.T  # Transpose to match expected format


    print("""
          
        =========================================
                PREPARING QUANTUM LAYER
        =========================================
        
        """)

    
    # Scale features to detuning range with more diagnostic info
    print(f"Scaling features with spectral value: {spectral}")
    xs = scale_to_detuning_range(xs_raw, spectral, args.detuning_max)
    print(f"Scaled feature range: {xs.min()} to {xs.max()}")
    
    # Scale test features to detuning range
    test_features = scale_to_detuning_range(test_features_raw, spectral, args.detuning_max)
    print(f"Scaled test feature range: {test_features.min()} to {test_features.max()}")

    # Create quantum layer (reuse if we already created one for guided autoencoder)
    if method_name == "guided_autoencoder" and 'quantum_layer' in locals():
        print("Reusing quantum layer from guided autoencoder...")
    else:
        quantum_layer = DetuningLayer(
            geometry=args.geometry,
            n_atoms=dim_reduction,
            lattice_spacing=args.lattice_spacing,
            rabi_freq=args.rabi_freq,
            t_end=args.evolution_time,
            n_steps=args.time_steps,
            readout_type=args.readout_type,
            encoding_scale=args.encoding_scale 
        )
   
    print("""
          
        =========================================
                 RUNNING QUANTUM LAYER
        =========================================
        
        """)
    
    print("Computing quantum embeddings for training data...")
    embeddings = quantum_layer.apply_layer(
        x=xs, 
        n_shots=args.n_shots, 
        show_progress=not args.no_progress
    )
    
    print("Computing quantum embeddings for test data...")
    test_embeddings = quantum_layer.apply_layer(
        test_features, 
        n_shots=args.n_shots, 
        show_progress=not args.no_progress
    )  

    
    print("""
          
        =========================================
             TRAINING LINEAR CLASSIFIER ON 
                   REDUCED FEATURES
        =========================================
        
        """)
    
    # Train different models
    results = {}
    
    loss_lin, accs_train_lin, accs_test_lin, model_lin = train(
        x_train=xs, 
        y_train=ys, 
        x_test=test_features, 
        y_test=test_targets, 
        regularization=args.regularization, 
        nepochs=args.nepochs, 
        batchsize=args.batchsize, 
        learning_rate=args.learning_rate,
        verbose=not args.no_progress,
        nonlinear=False
    )
    results[f"{reduction_name}+linear"] = (loss_lin, accs_train_lin, accs_test_lin, model_lin)
    
    print("""
          
        =========================================
             TRAINING LINEAR CLASSIFIER ON 
                   QUANTUM EMBEDDINGS
        =========================================
        
        """)
    
    loss_qrc, accs_train_qrc, accs_test_qrc, model_qrc = train(
        embeddings, ys, test_embeddings, test_targets, 
        regularization=args.regularization, 
        nepochs=args.nepochs, 
        batchsize=args.batchsize, 
        learning_rate=args.learning_rate,
        verbose=not args.no_progress,
        nonlinear=False
    )
    results["QRC"] = (loss_qrc, accs_train_qrc, accs_test_qrc, model_qrc)
    
    
    print("""
          
        =========================================
                TRAINING NEURAL NETWORK 
                  ON REDUCED FEATURES
        =========================================
        
        """)
    loss_nn, accs_train_nn, accs_test_nn, model_nn = train(
        xs, ys, test_features, test_targets, 
        regularization=args.regularization, 
        nepochs=args.nepochs, 
        batchsize=args.batchsize, 
        learning_rate=args.learning_rate,
        verbose=not args.no_progress,
        nonlinear=True
    )
    results[f"{reduction_name}+NN"] = (loss_nn, accs_train_nn, accs_test_nn, model_nn)
    

    
    print(f"""
        ==========================================
            Dataset: {args.dataset_type}
            Reduction Method: {reduction_name}
            Number of training samples: {data_train['metadata']['n_samples']}
            Number of test samples: {data_test['metadata']['n_samples']}
            Number of classes: {data_train['metadata']['n_classes']}
            Number of features: {dim_reduction}
            Number of epochs: {args.nepochs}
            Batch size: {args.batchsize}
            Learning rate: {args.learning_rate}
            Regularization: {args.regularization}
            Number of shots: {args.n_shots}
        ===========================================
          """)
    # Print and visualize results
    print_results(results)
    if not args.no_plot:
        plot_training_results(results)
    
    return results

if __name__ == "__main__":
    args = get_args()
    main(args)
