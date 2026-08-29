#if !defined(BINARY_SEARCH_TREE_H)
#define BINARY_SEARCH_TREE_H

namespace binary_search_tree {

class BinarySearchTree {
public:
    BinarySearchTree();
    ~BinarySearchTree();
    void insert(int data);
    bool search(int data) const;

private:
    struct Node {
        int data;
        Node* left;
        Node* right;
    };

    Node* root;
    void insert(Node*& node, int data);
    bool search(Node* node, int data) const;
};

}  // namespace binary_search_tree

#endif // BINARY_SEARCH_TREE_H
